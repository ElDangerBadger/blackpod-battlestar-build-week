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
                     'data': {'status': 'STALE', 'change_from_previous_close_pct': '1.25', 'day_volume': '2500',
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


class SynthesisPresentationTests(unittest.TestCase):
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
                         'First seen', 'Last seen', 'Day volume is not relative volume'):
            self.assertIn(expected, html)

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
