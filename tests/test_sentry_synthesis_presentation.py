"""No network, browser, models, or execution: retained synthesis rendering only."""
from copy import deepcopy
from html.parser import HTMLParser
import unittest

from blackpod_build_week.sentry_synthesis_presentation import render


def fixture():
    return {
        'status': 'CHALLENGED_INTERPRETATION', 'auto_trading': 'OFF',
        'newer_evidence_available': True,
        'operational': {'enabled': True, 'last_result': 'COMPLETED'},
        'report': {
            'completed_at': '2026-10-15T18:05:00Z',
            'authority': {'trade': False, 'allocation': False},
            'context': {
                'context_id': 'context-fixture', 'as_of': '2026-10-15T18:00:00Z',
                'watchlist': ['SPY', 'NVDA'],
                'source': {'head_sha256': 'a' * 64, 'capture_count': 4},
                'selection': {'selected_headline_count': 1, 'omitted_headline_count': 3},
                'portfolio': {'status': 'UNAVAILABLE_NO_VERIFIED_HOLDINGS'},
                'quality': {'headline_only': True, 'news_truncated': True,
                            'independent_sources_verified': False, 'source_count': 1,
                            'stale_context_count': 1, 'unavailable_context_count': 1,
                            'future_context_count': 1},
                'limitations': ['No article bodies retained.'],
                'evidence': [
                    {'evidence_id': 'headline-1', 'kind': 'HEADLINE', 'symbols': ['NVDA'],
                     'data': {'headline': 'Chipmaker announces agreement', 'source': 'Benzinga',
                              'url': 'https://example.com/story?a=1&b=2',
                              'published_at': '2026-10-15T16:00:00Z', 'updated_at': '2026-10-15T17:00:00Z',
                              'first_seen_at': '2026-10-15T17:05:00Z', 'last_seen_at': '2026-10-15T18:00:00Z'}},
                    {'evidence_id': 'price-1', 'kind': 'PRICE_CONTEXT', 'symbols': ['NVDA'],
                     'data': {'status': 'STALE', 'feed': 'iex', 'change_from_previous_close_pct': '1.25', 'day_volume': '2500',
                              'minute_at': '2026-10-15T17:00:00Z', 'day_bar_at': '2026-10-15T04:00:00Z',
                              'previous_day_bar_at': '2026-10-14T04:00:00Z'}},
                    {'evidence_id': 'quality-1', 'kind': 'FEED_QUALITY', 'symbols': [],
                     'data': {'news_truncated': True, 'source_count': 1}}],
            },
            'draft': {
                'schema_version': 'blackpod.sentry_oracle_draft.v1',
                'overview': {'text': 'Original interpretation of the agreement.', 'evidence_ids': ['headline-1']},
                'themes': [{
                    'theme_id': 'theme-1', 'title': 'Possible demand implication',
                    'interpretation': 'Demand could strengthen; evidence is incomplete.',
                    'evidence_ids': ['headline-1', 'price-1'],
                    'implications': [
                        {'symbol': 'NVDA', 'linkage': 'DIRECT_MENTION', 'trading': 'A short-lived catalyst may be possible.',
                         'investment': 'Business impact requires contract details.'},
                        {'symbol': 'SPY', 'linkage': 'HYPOTHETICAL_READ_THROUGH', 'trading': 'Index response is unverified.',
                         'investment': 'Broad read-through is speculative.'}],
                    'alternative': 'The agreement may already be expected.',
                    'proposed_invalidation': None, 'proposed_review_horizon': 'DAYS_TO_WEEKS'}],
                'unresolved_questions': ['Is revenue material?'],
            },
            'challenge': {
                'schema_version': 'blackpod.sentry_challenge.v1', 'draft_sha256': 'b' * 64,
                'reviews': [{'theme_id': 'theme-1', 'status': 'CONTESTED',
                             'reason': 'The headline supplies no revenue figure.', 'evidence_ids': ['headline-1'],
                             'alternative': 'This may be routine publicity.', 'missing_evidence': ['Original agreement terms']}],
                'overall_limitations': ['Single named news source.'],
            },
            'provenance': {
                'oracle': {'status': 'VALIDATED', 'provenance': {'provider': 'fixture', 'model': 'same-model', 'trace_id': 'oracle-1'}},
                'challenge': {'status': 'VALIDATED', 'provenance': {'provider': 'fixture', 'model': 'same-model', 'trace_id': 'challenge-1'}},
            },
        },
    }


class Tags(HTMLParser):
    def __init__(self, document):
        super().__init__()
        self.tags, self.attributes = [], []
        self.feed(document)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attributes.append((tag, dict(attrs)))


def evaluated_fixture():
    """Authored projection only; rendering never reads a live evaluation."""
    value = fixture()
    value['report']['report_id'] = 'sentry-synthesis-' + 'a' * 64
    criteria = ('evidence_support', 'economic_mechanism', 'alternatives', 'challenge',
                'missing_evidence', 'boundaries', 'clarity')
    value['narrative_evaluation'] = {'status': 'AVAILABLE', 'report': {
        'schema_version': 'blackpod.sentry_narrative_evaluation.v1',
        'evaluation_id': 'sentry-narrative-evaluation-' + 'e' * 64,
        'source_report_id': value['report']['report_id'], 'source_report_sha256': 'b' * 64,
        'packet_sha256': 'c' * 64, 'rubric_version': 'rubric-fixture-v1', 'rubric_sha256': 'd' * 64,
        'review_id': 'review-fixture', 'reviewed_at': '2026-10-16T03:30:00Z',
        'method': 'ASSISTANT_ADJUDICATION', 'reviewer': 'Assistant fixture',
        'summary': {'status': 'NEEDS_REVISION',
                    'criteria_counts': {'MEETS_RUBRIC': 1, 'PARTIAL': 4, 'NEEDS_WORK': 1, 'NOT_ASSESSED': 1},
                    'reviewed_claim_count': 1, 'claim_count': 2, 'mechanical_finding_count': 1},
        'criteria': [{'criterion_id': identity, 'assessment': assessment,
                      'rationale': 'Citation support requires a source-grounding judgment.',
                      'evidence_ids': ['headline-1']}
                     for identity, assessment in zip(criteria,
                         ('PARTIAL', 'NOT_ASSESSED', 'NEEDS_WORK', 'PARTIAL', 'PARTIAL', 'MEETS_RUBRIC', 'PARTIAL'))],
        'claims': [{'claim_text': 'Demand could strengthen; evidence is incomplete.',
                    'claim_path': '/draft/themes/0/interpretation', 'symbol': None, 'lens': 'THEME',
                    'cited_evidence_ids': ['headline-1'], 'assessment': 'PARTIALLY_SUPPORTED',
                    'rationale': 'The headline supports a reported agreement, not its economic size.',
                    'packet_evidence_ids': ['headline-1'], 'needed_evidence': ['Agreement economics']}],
        'mechanical': {'findings': [{'code': 'REPEATED_SENTENCE', 'paths': ['/draft/overview/text'],
                                    'evidence_ids': [], 'detail': 'An exact normalized sentence repeats.'}],
                       'coverage': {'watchlist': ['SPY', 'NVDA'], 'mentioned_symbols': ['NVDA'],
                                    'unmentioned_symbols': ['SPY'], 'headline_count': 1,
                                    'stale_context_count': 1, 'source_count': 1},
                       'unspecified': {'trading_count': 0, 'investment_count': 0,
                                       'horizon_count': 0, 'invalidation_count': 1},
                       'limitations': ['Mechanical checks do not decide semantic meaning.']},
        'limitations': ['Assistant assessment is not independent economic evidence.'],
        'authority': {'authorization_enabled': False, 'execution_enabled': False,
                      'capital_activation_enabled': False, 'allocation_enabled': False,
                      'policy_changes_enabled': False},
    }}
    return value


def keyed_fixture():
    """Authored v3 response remains symbol keyed in the displayed source."""
    value = fixture()
    draft = value['report']['draft']
    draft['schema_version'] = 'blackpod.sentry_oracle_draft.v3'
    for theme in draft['themes']:
        rows = theme.pop('implications')
        theme['implications_by_symbol'] = {
            row['symbol']: {key: content for key, content in row.items() if key != 'symbol'}
            for row in rows}
        theme['proposed_invalidation'] = {'status': 'UNSPECIFIED', 'text': ''}
    return value


class SynthesisPresentationTests(unittest.TestCase):
    def test_symbol_keyed_source_renders_original_lenses_and_dissent_unchanged(self):
        value = keyed_fixture()
        before = deepcopy(value)
        html = render(value)
        for expected in ('NVDA', 'SPY', 'A short-lived catalyst may be possible.',
                         'Broad read-through is speculative.', 'CONTESTED',
                         'The headline supplies no revenue figure.', 'This may be routine publicity.'):
            self.assertIn(expected, html)
        self.assertEqual(html.count('class="implication"'), 2)
        self.assertNotIn('implications', value['report']['draft']['themes'][0])
        self.assertEqual(value, before)

    def test_symbol_validation_label_preserves_historical_packet_and_parent(self):
        value = keyed_fixture()
        value['report']['validation'] = {'purpose': 'EXPLICIT_SYMBOL_VALIDATION',
            'parent_report_id': 'sentry-synthesis-' + 'a' * 64,
            'parent_report_sha256': 'b' * 64,
            'transport_schema_version': 'blackpod.sentry_synthesis_transport.v10',
            'scope': 'MANUAL_RETAINED_EVIDENCE'}
        before = deepcopy(value)
        html = render(value)
        for expected in ('Explicit symbol-keyed validation', 'original saved headlines',
                         'not a fresh market assessment or a new forecast',
                         'failed parent attempt is preserved', 'Preserved parent attempt',
                         'EXPLICIT_SYMBOL_VALIDATION', 'CONTESTED', 'Auto-trading OFF'):
            self.assertIn(expected, html)
        self.assertEqual(value, before)

    def test_known_oracle_rejection_marks_challenge_not_run_and_keeps_raw_status(self):
        for status in ('REJECTED', 'FAILED'):
            with self.subTest(status=status):
                value = fixture()
                value['status'] = status
                value['report'].update(status=status, draft=None, challenge=None)
                value['report']['provenance']['oracle'] = {
                    'status': status, 'response': None, 'failure_code': 'MODELDOCK_NARRATIVE_SCHEMA_INVALID'}
                value['report']['provenance']['challenge'] = {
                    'status': 'UNCERTAIN', 'response': None, 'failure_code': 'ORACLE_NOT_ACCEPTED'}
                value['role_diagnostics'] = {'oracle': {
                    'reason': 'DUPLICATE_SYMBOL', 'rule': 'OTHER', 'field': 'UNCLASSIFIED'}}
                before = deepcopy(value)
                html = render(value)
                for expected in ('Not run — Oracle draft was rejected/failed',
                                 'Duplicate symbol in Oracle implications', 'DUPLICATE_SYMBOL',
                                 'No challenge review pass took place', 'ORACLE_NOT_ACCEPTED',
                                 '<dd>UNCERTAIN</dd>', 'Auto-trading OFF'):
                    self.assertIn(expected, html)
                self.assertNotIn('A separate review pass of the same evidence', html)
                self.assertNotIn('Original interpretation of the agreement.', html)
                self.assertEqual(value, before)

    def test_genuine_uncertain_challenge_is_not_labeled_not_run(self):
        value = fixture()
        value['status'] = 'DRAFT_ONLY'
        value['report']['challenge'] = None
        value['report']['provenance']['challenge'] = {
            'status': 'UNCERTAIN', 'response': None, 'failure_code': 'MODELDOCK_REQUEST_TIMEOUT'}
        html = render(value)
        self.assertIn('Challenge unavailable · review incomplete', html)
        self.assertIn('Any uncertain request remains uncertain', html)
        self.assertIn('MODELDOCK_REQUEST_TIMEOUT', html)
        self.assertIn('<dd>UNCERTAIN</dd>', html)
        self.assertNotIn('Not run', html)

    def test_uncertain_oracle_with_known_block_retains_oracle_uncertainty(self):
        value = fixture()
        value['status'] = 'UNCERTAIN'
        value['report'].update(status='UNCERTAIN', draft=None, challenge=None)
        value['report']['provenance']['oracle'] = {'status': 'UNCERTAIN',
            'response': None, 'failure_code': 'MODELDOCK_REQUEST_TIMEOUT'}
        value['report']['provenance']['challenge'] = {'status': 'UNCERTAIN',
            'response': None, 'failure_code': 'ORACLE_NOT_ACCEPTED'}
        html = render(value)
        self.assertIn('Synthesis state uncertain', html)
        self.assertIn('Not run — Oracle draft was not accepted', html)
        self.assertNotIn('Oracle draft was rejected/failed', html)
        self.assertIn('MODELDOCK_REQUEST_TIMEOUT', html)

    def test_failure_diagnostic_and_keyed_prose_are_escaped(self):
        injection = '<script>alert("x")</script>'
        value = keyed_fixture()
        value['report']['draft']['themes'][0]['implications_by_symbol']['NVDA']['trading'] = injection
        html = render(value)
        self.assertIn('&lt;script&gt;', html)
        self.assertNotIn('<script>', html)
        value['report']['draft'] = None
        value['role_diagnostics'] = {'oracle': {key: injection for key in ('reason', 'rule', 'field')}}
        html = render(value)
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertNotIn('Duplicate symbol in Oracle implications', html)

    def test_narrative_evaluation_compact_grid_claims_and_original_dissent(self):
        value = evaluated_fixture()
        before = deepcopy(value)
        html = render(value)
        tags = Tags(html)
        criteria = [attrs for tag, attrs in tags.attributes if tag == 'div'
                    and 'quality-criterion' in attrs.get('class', '').split()]
        self.assertEqual(len(criteria), 7)
        for expected in ('Needs revision', 'Claims / citations', 'Economic connection', 'Alternatives',
                         'Challenge', 'Missing evidence', 'Boundaries', 'Clarity', 'Meets rubric',
                         'Not assessed', 'Claims reviewed: 1 / 2', 'Mechanical observations: 1',
                         'Assistant adjudication of this saved brief', 'not verified truth',
                         'not decide whether a market interpretation is true or false',
                         'The headline supports a reported agreement', 'Agreement economics',
                         'REPEATED_SENTENCE', 'An exact normalized sentence repeats.',
                         'Symbols without a recorded implication: SPY', 'rubric-fixture-v1',
                         'Oct 15 · 08:30:00 PM PDT', 'Original interpretation of the agreement.',
                         'CONTESTED', 'This may be routine publicity.', 'Auto-trading OFF'):
            self.assertIn(expected, html)
        self.assertLess(html.index('Narrative quality'), html.index('Oracle · original interpretation'))
        self.assertEqual(value, before)
        self.assertFalse({'form', 'input', 'button', 'script', 'iframe', 'meter', 'progress'} & set(tags.tags))
        details = [attrs for tag, attrs in tags.attributes if tag == 'details'
                   and 'quality-detail' in attrs.get('class', '').split()]
        self.assertEqual(len(details), 4)
        self.assertTrue(all('open' not in attrs for attrs in details))

    def test_narrative_evaluation_never_attaches_other_report_or_missing_identity(self):
        for report_identity in ('sentry-synthesis-' + 'f' * 64, None, ''):
            with self.subTest(report_identity=report_identity):
                value = evaluated_fixture()
                value['report']['report_id'] = report_identity
                html = render(value)
                self.assertIn('A saved review belongs to another brief', html)
                self.assertNotIn('Claims reviewed:', html)
                self.assertNotIn('Agreement economics', html)
                self.assertIn('Original interpretation of the agreement.', html)
        value = evaluated_fixture()
        value['report'] = None
        html = render(value)
        self.assertIn('No verified synthesis to display', html)
        self.assertNotIn('Claims reviewed:', html)

    def test_narrative_evaluation_missing_unavailable_and_unknown_are_honest(self):
        for projection, expected in (
                (None, 'No narrative-quality review has been recorded'),
                ({'status': 'NOT_RECORDED', 'report': None}, 'No narrative-quality review has been recorded'),
                ({'status': 'UNAVAILABLE', 'report': None}, 'review could not be verified'),
                ({'status': 'NO_MATCHING_REVIEW', 'report': None}, 'belongs to another brief'),
                ({'status': 'AVAILABLE', 'report': None}, 'review could not be verified'),
                ({'status': 'UNKNOWN', 'report': None}, 'review could not be verified')):
            with self.subTest(projection=projection):
                value = fixture()
                value['narrative_evaluation'] = projection
                html = render(value)
                self.assertIn(expected, html)
                self.assertNotIn('Claims reviewed:', html)
                self.assertIn('Original interpretation of the agreement.', html)

    def test_narrative_evaluation_all_review_text_escaped_and_css_classes_closed(self):
        value = evaluated_fixture()
        evaluation = value['narrative_evaluation']['report']
        injection = '<script>alert("review")</script><img src=x onerror=alert(1)>'
        for key in ('evaluation_id', 'review_id', 'rubric_version', 'reviewer'):
            evaluation[key] = injection
        evaluation['criteria'][0].update(criterion_id=injection, rationale=injection, evidence_ids=[injection])
        evaluation['criteria'][1]['assessment'] = injection
        claim = evaluation['claims'][0]
        for key in ('claim_text', 'claim_path', 'symbol', 'lens', 'assessment', 'rationale'):
            claim[key] = injection
        for key in ('cited_evidence_ids', 'packet_evidence_ids', 'needed_evidence'):
            claim[key] = [injection]
        evaluation['mechanical']['findings'][0].update(code=injection, detail=injection,
                                                     paths=[injection], evidence_ids=[injection])
        evaluation['mechanical']['coverage']['unmentioned_symbols'] = [injection]
        evaluation['mechanical']['limitations'] = [injection]
        evaluation['limitations'] = [injection]
        html = render(value)
        self.assertNotIn(injection, html)
        self.assertNotIn('<script', html)
        self.assertNotIn('<img', html)
        self.assertIn('&lt;script&gt;', html)
        classes = [attrs['class'] for tag, attrs in Tags(html).attributes
                   if 'quality-criterion' in attrs.get('class', '').split()]
        self.assertTrue(all(set(value.split()) <= {'quality-criterion', 'meets', 'partial', 'needs-work', 'unassessed'}
                            for value in classes))

    def test_narrative_evaluation_rubric_success_is_not_approval_or_market_truth(self):
        value = evaluated_fixture()
        value['narrative_evaluation']['report']['summary']['status'] = 'MEETS_REVIEW_RUBRIC'
        html = render(value)
        self.assertIn('Meets review rubric', html)
        self.assertIn('No recommendations, authorizations, orders, allocation changes or experiment changes follow', html)
        self.assertIn('not verified truth, a market forecast, or evidence of a trading edge', html)
        self.assertIn('NOT TRADE AUTHORITY', html)

    def test_text_validation_keeps_original_clock_dissent_and_authority(self):
        value=fixture()
        value['report']['validation']={'purpose':'EXPLICIT_TEXT_VALIDATION',
            'parent_report_id':'sentry-synthesis-'+'a'*64,'parent_report_sha256':'b'*64,
            'transport_schema_version':'blackpod.sentry_synthesis_transport.v9','scope':'MANUAL_RETAINED_EVIDENCE'}
        html=render(value)
        for expected in ('Explicit text-format validation','MANUAL_RETAINED_EVIDENCE',
                         'not a fresh market assessment or a new forecast','CONTESTED','Auto-trading OFF'):
            self.assertIn(expected,html)

    def test_contract_validation_keeps_original_clock_dissent_and_authority(self):
        value=fixture()
        value['report']['validation']={'purpose':'EXPLICIT_CONTRACT_VALIDATION',
            'parent_report_id':'sentry-synthesis-'+'a'*64,'parent_report_sha256':'b'*64,
            'transport_schema_version':'blackpod.sentry_synthesis_transport.v8','scope':'MANUAL_RETAINED_EVIDENCE'}
        html=render(value)
        for expected in ('Explicit contract validation','MANUAL_RETAINED_EVIDENCE',
                         'not a fresh market assessment or a new forecast','CONTESTED','Auto-trading OFF'):
            self.assertIn(expected,html)

    def test_host_rejection_is_explicit_without_an_accepted_draft(self):
        value=fixture()
        value['status']='REJECTED'
        value['report'].update(status='REJECTED',draft=None,challenge=None)
        value['report']['provenance']['oracle']={'status':'REJECTED',
            'failure_code':'MODELDOCK_NARRATIVE_SCHEMA_INVALID','response':None,'provenance':None}
        html=render(value)
        for expected in ('Synthesis response rejected','Oracle draft unavailable','MODELDOCK_NARRATIVE_SCHEMA_INVALID'):
            self.assertIn(expected,html)
        self.assertNotIn('Original interpretation of the agreement.',html)

    def test_output_budget_validation_keeps_original_clock_and_dissent(self):
        value=fixture()
        value['report']['validation']={'purpose':'EXPLICIT_OUTPUT_BUDGET_VALIDATION',
            'parent_report_id':'sentry-synthesis-'+'a'*64,'parent_report_sha256':'b'*64,
            'transport_schema_version':'blackpod.sentry_synthesis_transport.v7','scope':'MANUAL_RETAINED_EVIDENCE'}
        html=render(value)
        for expected in ('Explicit output-budget validation','MANUAL_RETAINED_EVIDENCE',
                         'not a fresh market assessment or a new forecast','CONTESTED','Auto-trading OFF'):
            self.assertIn(expected,html)

    def test_model_selection_validation_preserves_original_time_and_dissent(self):
        value=fixture()
        value['report']['validation']={'purpose':'EXPLICIT_MODEL_SELECTION_VALIDATION',
            'parent_report_id':'sentry-synthesis-'+'a'*64,'parent_report_sha256':'b'*64,
            'transport_schema_version':'blackpod.sentry_synthesis_transport.v6','scope':'MANUAL_RETAINED_EVIDENCE'}
        html=render(value)
        for expected in ('Explicit model-selection validation','MANUAL_RETAINED_EVIDENCE',
                         'not a fresh market assessment or a new forecast','CONTESTED','Auto-trading OFF'):
            self.assertIn(expected,html)

    def test_background_budget_and_manual_diagnostics_are_distinct(self):
        value=fixture()
        value['operational'].update(background_attempt_count_today=1,manual_attempt_count_today=6,attempt_count_today=7)
        html=render(value)
        self.assertIn('Background attempts today: 1/4',html)
        self.assertIn('Explicit manual diagnostics: 6',html)
        self.assertIn('separate schedule allowance',html)

    def test_runtime_diagnostic_retains_original_clock_and_shadow_authority(self):
        value=fixture()
        value['report']['validation']={'purpose':'EXPLICIT_RUNTIME_DIAGNOSTIC',
            'parent_report_id':'sentry-synthesis-'+'a'*64,'parent_report_sha256':'b'*64,
            'transport_schema_version':'blackpod.sentry_synthesis_transport.v5','scope':'MANUAL_RETAINED_EVIDENCE'}
        html=render(value)
        for expected in ('Explicit runtime diagnostic','MANUAL_RETAINED_EVIDENCE',
                         'not a fresh market assessment or a new forecast','CONTESTED','Auto-trading OFF'):
            self.assertIn(expected,html)

    def test_error_code_diagnostic_is_historical_and_not_a_new_forecast(self):
        value = fixture()
        value['report']['validation'] = {'purpose':'EXPLICIT_ERROR_CODE_DIAGNOSTIC',
            'parent_report_id':'sentry-synthesis-'+'a'*64,'parent_report_sha256':'b'*64,
            'transport_schema_version':'blackpod.sentry_synthesis_transport.v4','scope':'MANUAL_RETAINED_EVIDENCE'}
        html = render(value)
        for expected in ('Explicit error-code diagnostic','MANUAL_RETAINED_EVIDENCE',
                         'Retained inputs from Oct 15 · 11:00:00 AM PDT',
                         'not a fresh market assessment or a new forecast','CONTESTED','Auto-trading OFF'):
            self.assertIn(expected,html)
        self.assertNotIn('Explicit deadline validation',html)

    def test_deadline_validation_is_manual_historical_and_preserves_dissent(self):
        value = fixture()
        value['report']['validation'] = {'purpose':'EXPLICIT_DEADLINE_VALIDATION',
            'parent_report_id':'sentry-synthesis-'+'a'*64,'parent_report_sha256':'b'*64,
            'transport_schema_version':'blackpod.sentry_synthesis_transport.v3','scope':'MANUAL_RETAINED_EVIDENCE'}
        html = render(value)
        for expected in ('Explicit deadline validation', 'MANUAL_RETAINED_EVIDENCE',
                         'explicit manual check; normal monitoring hours and frequency are unchanged',
                         'not a fresh market assessment or a new forecast', 'CONTESTED', 'Auto-trading OFF'):
            self.assertIn(expected, html)
        self.assertNotIn('Explicit v2 compatibility validation', html)

    def test_reserved_attempt_does_not_masquerade_as_the_old_completed_report(self):
        value = fixture()
        value['operational']['last_result'] = 'ATTEMPT_STARTED'
        html = render(value)
        self.assertIn('awaiting a retained completion', html)
        self.assertIn('Any report below is from an earlier completed attempt', html)
        self.assertIn('does not establish model progress', html)
        self.assertIn('Original interpretation of the agreement.', html)

    def test_v2_validation_keeps_evidence_and_completion_clocks_distinct(self):
        value = fixture()
        value['report']['validation'] = {'purpose': 'EXPLICIT_V2_VALIDATION',
            'parent_report_id': 'sentry-synthesis-'+'a'*64, 'parent_report_sha256': 'b'*64,
            'transport_schema_version': 'blackpod.sentry_synthesis_transport.v2'}
        before = deepcopy(value)
        html = render(value)
        for expected in ('Explicit v2 compatibility validation', 'Retained inputs from Oct 15 · 11:00:00 AM PDT',
                         'not a fresh market assessment or a new forecast', 'failed parent attempt is preserved',
                         'Validation completed', '11:05:00 AM PDT', 'Preserved parent attempt',
                         'sentry-synthesis-'+'a'*64, 'b'*64, 'CONTESTED', 'stale', 'Auto-trading OFF'):
            self.assertIn(expected, html)
        self.assertEqual(value, before)
        ordinary = fixture()
        self.assertNotIn('Explicit v2 compatibility validation', render(ordinary))

    def test_original_and_contested_challenge_both_visible_without_approval(self):
        value = fixture()
        original = deepcopy(value)
        html = render(value)
        for expected in ('Original interpretation of the agreement.', 'Demand could strengthen;',
                         'CONTESTED', 'The headline supplies no revenue figure.', 'This may be routine publicity.',
                         'Original agreement terms', 'Original alternative explanation',
                         'NOT TRADE AUTHORITY', 'not verified truth or approval'):
            self.assertIn(expected, html)
        self.assertLess(html.index('Demand could strengthen;'), html.index('The headline supplies no revenue figure.'))
        self.assertEqual(value, original)

    def test_separate_trading_investment_and_readthrough_lenses(self):
        html = render(fixture())
        for expected in ('Trading lens', 'Investment lens', 'Provider symbol tag · textual connection unverified',
                         'Hypothetical read-through · not established', 'Business impact requires contract details.',
                         'Broad read-through is speculative.', 'not a portfolio assessment',
                         'Proposed review horizon:', 'not an approved investment horizon',
                         'Not specified; not invented.'):
            self.assertIn(expected, html)

    def test_quality_constraints_and_newer_evidence_are_visible(self):
        html = render(fixture())
        for expected in ('Headline-only evidence', 'Single named news source', 'News pages are truncated.',
                         'Coverage is incomplete', '1 price context(s) are stale',
                         '1 price context(s) are unavailable', '1 price context(s) are future-dated',
                         'Newer Sentry evidence exists', 'does not establish truth',
                         'Independent sources are not verified', 'not a live view',
                         'performance relative to SPY/QQQ'):
            self.assertIn(expected, html)

    def test_source_links_and_all_timestamp_fields_are_retained(self):
        html = render(fixture())
        tags = Tags(html)
        links = [attrs for tag, attrs in tags.attributes if tag == 'a']
        source = next(attrs for attrs in links if attrs.get('href', '').startswith('https:'))
        self.assertEqual(source['href'], 'https://example.com/story?a=1&b=2')
        self.assertEqual(source['rel'], 'noopener noreferrer')
        self.assertEqual(source['target'], '_blank')
        self.assertIn('href="#evidence-0"', html)
        for expected in ('11:00:00 AM PDT', '11:05:00 AM PDT', '09:00:00 AM PDT', '10:00:00 AM PDT',
                         '10:05:00 AM PDT', '09:00:00 PM PDT', 'Minute bar:', 'Previous daily bar:',
                         'First seen', 'Last seen', 'shares from IEX only, not total market volume'):
            self.assertIn(expected, html)

    def test_volume_scope_is_iex_only_without_rewriting_saved_evidence(self):
        value = fixture()
        value['report']['context']['evidence'][1]['data']['day_volume'] = '501362'
        before = deepcopy(value)
        html = render(value)
        self.assertIn('IEX-only volume: 501362 shares', html)
        self.assertIn('shares from IEX only, not total market volume', html)
        self.assertIn('Volume is not relative volume', html)
        self.assertIn('Saved bars may be stale or incomplete', html)
        self.assertIn('Original price context · STALE', html)
        self.assertIn('Minute bar:', html)
        self.assertIn('Daily bar start:', html)
        self.assertNotIn('Day volume', html)
        self.assertEqual(value, before)

    def test_new_consolidated_context_is_separate_from_original_iex_evidence(self):
        for feed, delay, badge in (('sip', 0, 'Consolidated SIP'),
                                   ('delayed_sip', 900, 'Consolidated SIP · 15-minute delayed')):
            with self.subTest(feed=feed):
                value = fixture()
                value['report']['context']['evidence'][1]['data']['day_volume'] = '501362'
                value['current_market_context'] = {
                    'status': 'FRESH', 'captured_at': '2026-10-15T22:00:00Z',
                    'market_feed': feed, 'feed_delay_seconds': delay,
                    'contexts': [{'symbol': 'NVDA', 'status': 'DELAYED' if delay else 'OBSERVED', 'feed': feed,
                                  'feed_delay_seconds': delay, 'day_volume': '19243640',
                                  'price': '100.125', 'change_from_previous_close_pct': '2.50',
                                  'minute_at': '2026-10-15T21:44:00Z'}]}
                before = deepcopy(value)
                html = render(value)
                current = html.split('class="card current-market-context"', 1)[1].split('</section>', 1)[0]
                self.assertIn(badge, current)
                self.assertIn('Market volume <b>19,243,640</b> shares', current)
                self.assertIn('Saved price 100.125', current)
                self.assertIn('+2.50%', current)
                self.assertIn('DELAYED' if delay else 'OBSERVED', current)
                self.assertIn('02:44:00 PM PDT', current)
                self.assertIn('03:00:00 PM PDT', current)
                self.assertIn('separate from the original brief inputs', current)
                self.assertIn('do not update the Oracle interpretation or its review', current)
                self.assertNotIn('IEX', current)
                historical = html.split('class="card source-folder"', 1)[1]
                self.assertIn('original historical snapshot', historical)
                self.assertIn('IEX-only volume: 501362 shares', historical)
                self.assertIn('Historical IEX', historical)
                self.assertNotIn('19,243,640', historical)
                self.assertIn('Original interpretation of the agreement.', html)
                self.assertIn('The headline supplies no revenue figure.', html)
                self.assertLess(html.index('Current market context'), html.index('Oracle · original interpretation'))
                self.assertEqual(value, before)

    def test_current_market_context_does_not_promote_unknown_or_legacy_feed(self):
        for feed, delay in (('iex', 0), ('unknown', 0), ('sip', 900), ('delayed_sip', 0)):
            with self.subTest(feed=feed, delay=delay):
                value = fixture()
                value['current_market_context'] = {
                    'status': 'FRESH', 'captured_at': '2026-10-15T22:00:00Z',
                    'market_feed': feed, 'feed_delay_seconds': delay,
                    'contexts': [{'symbol': 'NVDA', 'feed': feed, 'feed_delay_seconds': delay,
                                  'status': 'OBSERVED', 'day_volume': '19243640'}]}
                html = render(value)
                current = html.split('class="card current-market-context"', 1)[1].split('</section>', 1)[0]
                self.assertIn('Consolidated market context is unavailable', current)
                self.assertNotIn('19,243,640', current)
                self.assertNotIn('IEX-only volume', current)
                self.assertIn('IEX-only volume: 2500 shares', html)

    def test_unknown_naive_and_invalid_source_times_never_gain_a_timezone(self):
        value = fixture()
        value['report']['completed_at'] = '2026-10-15T12:00:00'
        value['report']['context']['as_of'] = 'not a timestamp'
        value['report']['context']['evidence'][0]['data']['published_at'] = None
        html = render(value)
        self.assertNotIn('12:00:00 PM', html)
        self.assertGreaterEqual(html.count('Unavailable'), 3)

    def test_dst_uses_los_angeles_not_execution_host_timezone(self):
        value = fixture()
        value['report']['context']['as_of'] = '2026-11-15T18:00:00Z'
        self.assertIn('10:00:00 AM PST', render(value))

    def test_no_report_has_no_fixture_or_inferred_draft(self):
        for status in ('NOT_GENERATED', 'UNAVAILABLE', 'FAILED', 'UNCERTAIN'):
            with self.subTest(status=status):
                html = render({'status': status, 'report': None, 'auto_trading': 'OFF'})
                self.assertIn('No verified synthesis to display', html)
                self.assertIn('No sample interpretation or substitute report', html)
                self.assertNotIn('Original interpretation of the agreement.', html)
                self.assertNotIn('No themes were supported', html)

    def test_missing_draft_and_challenge_are_explicit(self):
        value = fixture()
        value['status'] = 'DRAFT_ONLY'
        value['report']['challenge'] = None
        html = render(value)
        self.assertIn('Original interpretation of the agreement.', html)
        self.assertIn('Challenge unavailable · review incomplete', html)
        self.assertNotIn('CONTESTED', html)
        value['report']['draft'] = None
        html = render(value)
        self.assertIn('Oracle draft unavailable', html)
        self.assertIn('Attempt recorded', html)
        self.assertIn('Retained attempt age:', render({**value, 'brief_age_seconds': 60}))
        self.assertNotIn('original draft preserved', html)
        self.assertNotIn('Original interpretation of the agreement.', html)

    def test_zero_themes_remains_no_themes_without_invented_conclusions(self):
        value = fixture()
        value['report']['draft']['themes'] = []
        value['report']['draft']['unresolved_questions'] = []
        value['report']['challenge']['reviews'] = []
        html = render(value)
        self.assertIn('No themes were supported in the model draft', html)
        self.assertIn('does not establish an absence of market events', html)
        self.assertNotIn('Possible demand implication', html)

    def test_off_is_never_inferred_from_missing_or_unknown_runtime(self):
        for auto in (None, 'ON', 'UNKNOWN', '<script>OFF</script>'):
            with self.subTest(auto=auto):
                value = {'status': 'NOT_GENERATED', 'auto_trading': auto}
                html = render(value)
                self.assertIn('Auto-trading UNVERIFIED', html)
                self.assertNotIn('Auto-trading OFF', html)

    def test_actual_provenance_only_no_claim_of_independent_models(self):
        html = render(fixture())
        self.assertEqual(html.count('same-model'), 2)
        self.assertIn('oracle-1', html)
        self.assertIn('challenge-1', html)
        self.assertIn('not independent-source or independent-model consensus', html)
        value = fixture()
        value['report']['provenance'] = {}
        html = render(value)
        self.assertEqual(html.count('Model identity metadata unavailable'), 2)
        self.assertNotIn('same-model', html)

    def test_readonly_markup_no_forms_scripts_or_provider_calls(self):
        html = render(fixture())
        tags = Tags(html)
        self.assertFalse({'form', 'input', 'button', 'script', 'iframe'} & set(tags.tags))
        refresh = next(attrs for tag, attrs in tags.attributes if tag == 'meta' and attrs.get('http-equiv') == 'refresh')
        self.assertEqual(refresh['content'], '60')
        for expected in ('href="/sentry"', 'href="/sentry-audit"', 'does not collect news or run models',
                         'frozen reversal experiment is separate and unchanged'):
            self.assertIn(expected, html)

    def test_untrusted_headline_model_review_metadata_and_id_are_escaped(self):
        value = fixture()
        injection = '<script>alert("x")</script><img src=x onerror=alert(1)>'
        report = value['report']
        report['draft']['overview']['text'] = injection
        report['draft']['themes'][0]['title'] = injection
        report['draft']['themes'][0]['implications'][0]['trading'] = injection
        report['challenge']['reviews'][0]['reason'] = injection
        report['provenance']['oracle']['provenance']['model'] = injection
        report['context']['evidence'][0]['data']['headline'] = injection
        report['context']['evidence'][0]['data']['source'] = injection
        report['context']['evidence'][0]['evidence_id'] = injection
        report['context']['evidence'][2]['data'] = {injection: injection}
        report['context']['context_id'] = injection
        report['context']['limitations'] = [injection]
        value['operational']['last_result'] = injection
        html = render(value)
        self.assertNotIn(injection, html)
        self.assertNotIn('<script', html)
        self.assertNotIn('<img', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertNotIn('script', Tags(html).tags)
        self.assertIn('id="evidence-0"', html)

    def test_unsafe_schemes_credentials_malformed_and_control_urls_are_not_links(self):
        for url in ('javascript:alert(1)', 'http://example.com', '//example.com',
                    'https://user:password@example.com', 'https://[malformed',
                    'https://example.com/\nmalicious', 'data:text/html,test'):
            with self.subTest(url=url):
                value = fixture()
                value['report']['context']['evidence'][0]['data']['url'] = url
                html = render(value)
                links = [attrs.get('href') for tag, attrs in Tags(html).attributes if tag == 'a']
                self.assertFalse(any(target.startswith(('https:', 'http:', 'javascript:', 'data:')) for target in links))
                self.assertIn('Chipmaker announces agreement', html)

    def test_missing_citation_does_not_create_a_fabricated_link(self):
        value = fixture()
        value['report']['draft']['overview']['evidence_ids'] = ['absent']
        html = render(value)
        self.assertIn('absent (unavailable)', html)
        self.assertNotIn('href="#absent"', html)

    def test_retained_brief_age_keeps_original_cutoff_and_flags_over_one_hour(self):
        value = fixture()
        value['brief_age_seconds'] = 3661
        html = render(value)
        self.assertIn('Retained brief age: 61.0 minutes', html)
        self.assertIn('more than one hour old', html)
        self.assertIn('historical interpretation, not a current market assessment', html)
        self.assertIn('11:00:00 AM PDT', html)
        self.assertIn('11:05:00 AM PDT', html)
        value['brief_age_seconds'] = 3600
        html = render(value)
        self.assertIn('Retained brief age: 60.0 minutes', html)
        self.assertNotIn('more than one hour old', html)
        for age in (None, -1, True, '3601', float('inf')):
            with self.subTest(age=age):
                value['brief_age_seconds'] = age
                html = render(value)
                self.assertIn('Retained brief age: unavailable', html)
                self.assertNotIn('more than one hour old', html)

    def test_blocked_worker_result_and_attempt_time_do_not_hide_retained_evidence(self):
        for result in ('SOURCE_OR_OFF_BLOCKED', 'NO_NEW_HEADLINE_EVIDENCE'):
            with self.subTest(result=result):
                value = fixture()
                value['operational'].update(last_result=result, last_attempt_at='2026-10-15T18:10:00Z',
                                            attempt_count_today=2)
                html = render(value)
                self.assertIn(result, html)
                self.assertIn('11:10:00 AM PDT', html)
                self.assertIn('Attempts today: 2', html)
                self.assertIn('Original interpretation of the agreement.', html)
                self.assertIn('11:00:00 AM PDT', html)

    def test_citations_have_compact_human_labels_and_original_anchors(self):
        value = fixture()
        value['report']['draft']['overview']['evidence_ids'] = ['headline-1', 'price-1', 'quality-1']
        html = render(value)
        for expected in ('href="#evidence-0">Headline 1</a>',
                         'href="#evidence-1">NVDA price context</a>',
                         'href="#evidence-2">Feed quality</a>'):
            self.assertIn(expected, html)
        for number, identity in enumerate(('headline-1', 'price-1', 'quality-1')):
            self.assertIn('id="evidence-' + str(number) + '"', html)
            self.assertIn(identity, html)
        self.assertNotIn('href="#evidence-0">headline-1</a>', html)

    def test_limits_and_sources_are_closed_details_with_clear_summaries(self):
        html = render(fixture())
        details = [attrs for tag, attrs in Tags(html).attributes if tag == 'details']
        limits = next(attrs for attrs in details if 'evidence-limits' in attrs.get('class', '').split())
        sources = next(attrs for attrs in details if 'source-folder' in attrs.get('class', '').split())
        self.assertNotIn('open', limits)
        self.assertNotIn('open', sources)
        self.assertIn('Headlines only · coverage incomplete · no verified holdings', html)
        self.assertIn('Source evidence · 3 retained item(s)', html)
        self.assertIn('Full evidence IDs are retained below', html)
        self.assertLess(html.index('The headline supplies no revenue figure.'), html.index('class="card source-folder"'))
        self.assertLess(html.index('Unverified headline-based interpretation.'), html.index('Oracle · original interpretation'))

    def test_unknown_coverage_summary_does_not_imply_completeness(self):
        value = fixture()
        value['report']['context']['quality']['news_truncated'] = False
        html = render(value)
        self.assertIn('Headlines only · coverage unknown · no verified holdings', html)
        self.assertIn('Independent sources are not verified', html)
        self.assertIn('Holdings and desk exposures are unavailable', html)

    def test_versioned_invalidation_objects_render_without_dict_prose(self):
        value = fixture()
        theme = value['report']['draft']['themes'][0]
        theme['proposed_invalidation'] = {'status': 'UNSPECIFIED', 'text': ''}
        self.assertIn('Not specified; not invented.', render(value))
        theme['proposed_invalidation'] = {'status': 'PROPOSED', 'text': '<Primary evidence contradicts the interpretation>'}
        html = render(value)
        self.assertIn('&lt;Primary evidence contradicts the interpretation&gt;', html)
        self.assertNotIn("&#x27;status&#x27;", html)

    def test_failed_processing_reason_is_visible_without_substitute_draft(self):
        value = fixture()
        value.update(status='FAILED')
        value['report']['draft'] = None
        value['report']['challenge'] = None
        value['report']['provenance']['oracle'] = {'status': 'FAILED', 'failure_code': 'MODELDOCK_HTTP_422'}
        html = render(value)
        self.assertIn('Processing result: MODELDOCK_HTTP_422', html)
        self.assertIn('Oracle draft unavailable', html)
        self.assertNotIn('Original interpretation of the agreement.', html)

    def test_human_citation_labels_escape_untrusted_symbols(self):
        value = fixture()
        value['report']['context']['evidence'][1]['symbols'] = ['<script>NVDA</script>']
        html = render(value)
        self.assertIn('&lt;script&gt;NVDA&lt;/script&gt; price context</a>', html)
        self.assertNotIn('<script>', html)
        self.assertIn('href="#evidence-1"', html)


if __name__ == '__main__':
    unittest.main()
