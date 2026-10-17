"""Offline narrative adjudication over immutable, explicitly authored fixtures.

No collector, credentials, provider or inference is used. The service integration
uses the real ModelDock client with an in-memory HTTP response fixture.
"""
from copy import deepcopy
from datetime import timedelta
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week import sentry_catalyst as catalyst
from blackpod_build_week import sentry_narrative_evaluation as narrative
from blackpod_build_week import sentry_synthesis as synthesis
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.modeldock_client import ModelDockClient, UrlLibTransport
from test_sentry_catalyst import NOW, packet as capture_packet
import test_sentry_synthesis_core as core_fixture


def recompose(report, *, draft=None, challenge=None):
    """Refresh genuine content identities after an authored fixture variation."""
    oracle = deepcopy(report['provenance']['oracle'])
    challenger = deepcopy(report['provenance']['challenge'])
    oracle['response'] = deepcopy(draft if draft is not None else report['draft'])
    challenger['response'] = deepcopy(challenge if challenge is not None else report['challenge'])
    challenger['response']['draft_sha256'] = sha256_bytes(canonical_json_bytes(oracle['response']))
    return synthesis.compose_report(deepcopy(report['context']), oracle, challenger,
                                    report['completed_at'])


def keyed_report(report):
    draft = deepcopy(report['draft'])
    draft['schema_version'] = 'blackpod.sentry_oracle_draft.v3'
    for theme in draft['themes']:
        rows = theme.pop('implications')
        theme['implications_by_symbol'] = {
            row['symbol']: {key: value for key, value in row.items() if key != 'symbol'}
            for row in rows}
    return recompose(report, draft=draft)


def review_fixture(report, **changes):
    evidence = [row['evidence_id'] for row in report['context']['evidence']
                if row['kind'] == 'HEADLINE']
    value = {
        'schema_version': 'blackpod.sentry_narrative_review.v1',
        'rubric_version': 'blackpod.sentry_narrative_rubric.v1',
        'review_id': 'offline-fixture-001',
        'reviewed_at': catalyst.stamp(NOW + timedelta(hours=2)),
        'reviewer': 'Offline fixture adjudicator',
        'method': 'ASSISTANT_ADJUDICATION',
        'source_report_id': report['report_id'],
        'source_report_sha256': sha256_bytes(canonical_json_bytes(report)),
        'packet_sha256': sha256_bytes(canonical_json_bytes(report['context'])),
        'criteria': [{'criterion_id': identity, 'assessment': 'PARTIAL',
                      'rationale': 'Authored rubric assessment; limited headline evidence.',
                      'evidence_ids': evidence} for identity in narrative.RUBRIC_IDS],
        'claims': [{'claim_path': claim['claim_path'], 'assessment': 'PARTIALLY_SUPPORTED',
                    'rationale': 'This fixture distinguishes the headline from its possible economic implication.',
                    'packet_evidence_ids': evidence,
                    'needed_evidence': ['Independent primary disclosure and quantified materiality.']}
                   for claim in narrative.claim_catalog(report)],
        'later_context': [],
    }
    value.update(changes)
    return value


class NarrativeFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Real packet construction and response contracts, without a service call.
        with tempfile.TemporaryDirectory(dir='/private/tmp') as directory:
            store = catalyst.CatalystStore(Path(directory) / 'evidence')
            store.append(*capture_packet())
            records, verification = store.verified_records()
            packet = synthesis.build_packet(records, verification, NOW + timedelta(hours=1))
            fixture = core_fixture.SynthesisCoreTests('test_composed_report_preserves_original_draft_and_dissent_without_authority')
            oracle, challenge = fixture.model_results(packet)
            cls.source = synthesis.compose_report(packet, oracle, challenge,
                                                  catalyst.stamp(NOW + timedelta(hours=1, seconds=30)))

    def setUp(self):
        self.report = deepcopy(self.source)
        self.review = review_fixture(self.report)


class SentryNarrativeContractTests(NarrativeFixture):
    def test_legacy_catalog_mechanical_and_evaluation_bytes_match_v1_baseline(self):
        # Recorded against the previous HEAD implementation before this v3
        # adapter. Existing immutable evaluations must keep their exact bytes.
        projections = [(narrative.claim_catalog(self.report),
                        'eced277314913083b1b410c7c17952325a29334fb76a723973cbb27b35f3292b'),
                       (narrative.mechanical_review(self.report),
                        '9d5975e586cb5e9d948eb1a9c6cf63405f0259b014122bcae4fbc4cdcc47d670'),
                       (narrative.build_evaluation(self.report, self.review),
                        'e924bb44b25316ffed3bfcc64d7ce55fba9acde637cd60b02ca6538cdaa50da0')]
        for value, expected in projections:
            self.assertEqual(sha256_bytes(canonical_json_bytes(value)), expected)
        self.assertEqual(narrative.evaluation_id(self.review),
            'narrative-eval-5c95e5bd903bb9df874d91e32e2b43180802b493eeb8cb033eaf776c6cca987d')

    def test_keyed_claim_catalog_uses_exact_original_symbol_paths_and_prose(self):
        report = keyed_report(self.report)
        before = canonical_json_bytes(report)
        claims = narrative.claim_catalog(report)
        expected_paths = {f'/draft/themes/0/implications_by_symbol/SPY/{lens}'
                          for lens in ('trading', 'investment')}
        self.assertEqual({row['claim_path'] for row in claims}, expected_paths)
        for row in claims:
            self.assertEqual(row['symbol'], 'SPY')
            self.assertEqual(row['claim_text'],
                report['draft']['themes'][0]['implications_by_symbol']['SPY'][row['lens']])
        self.assertEqual(canonical_json_bytes(report), before)
        self.assertNotIn('implications', report['draft']['themes'][0])

    def test_keyed_review_binds_original_source_and_rejects_normalized_array_paths(self):
        report = keyed_report(self.report)
        before = deepcopy(report)
        review = review_fixture(report)
        result = narrative.build_evaluation(report, review)
        self.assertEqual(report, before)
        self.assertEqual(result['source_report_sha256'], sha256_bytes(canonical_json_bytes(before)))
        self.assertTrue(all('/implications_by_symbol/SPY/' in row['claim_path']
                            for row in result['claims']))
        review['claims'][0]['claim_path'] = '/draft/themes/0/implications/0/trading'
        with self.assertRaises(ValueError):
            narrative.validate_review(review, report)

    def test_review_is_strict_detached_and_deterministic(self):
        before = deepcopy((self.review, self.report))
        validated = narrative.validate_review(self.review, self.report)
        self.assertEqual(validated, self.review)
        self.assertEqual((self.review, self.report), before)
        validated['criteria'][0]['rationale'] = 'Detached local variation.'
        self.assertEqual((self.review, self.report), before)
        self.assertEqual(narrative.build_evaluation(self.report, self.review),
                         narrative.build_evaluation(self.report, deepcopy(self.review)))

    def test_catalog_preserves_original_claim_text_and_inherited_citations(self):
        claims = narrative.claim_catalog(self.report)
        self.assertEqual(len(claims), 2)
        implication = self.report['draft']['themes'][0]['implications'][0]
        for claim in claims:
            self.assertEqual(set(claim), {'claim_path', 'symbol', 'lens', 'claim_text', 'cited_evidence_ids'})
            self.assertEqual(claim['symbol'], 'SPY')
            self.assertEqual(claim['claim_text'], implication[claim['lens'].lower()])
            self.assertEqual(claim['cited_evidence_ids'], self.report['draft']['themes'][0]['evidence_ids'])
            self.assertTrue(claim['claim_path'].startswith('/draft/themes/0/implications/0/'))

    def test_unspecified_claims_are_not_invented(self):
        draft = deepcopy(self.report['draft'])
        draft['themes'][0]['implications'][0].update(trading='UNSPECIFIED', investment='UNSPECIFIED')
        report = recompose(self.report, draft=draft)
        self.assertEqual(narrative.claim_catalog(report), [])
        mechanical = narrative.mechanical_review(report)
        self.assertEqual(mechanical['unspecified'], {
            'trading_count': 1, 'investment_count': 1,
            'horizon_count': 1, 'invalidation_count': 1})
        value = narrative.build_evaluation(report, review_fixture(report))
        self.assertEqual(value['claims'], [])

    def test_unknown_prose_remains_original_prose_not_inferred_unspecified(self):
        # Literal contract sentinel only: vague original text must still be reviewed.
        self.assertEqual(len(narrative.claim_catalog(self.report)), 2)
        self.assertEqual(narrative.mechanical_review(self.report)['unspecified']['trading_count'], 0)

    def test_claim_review_must_cover_each_original_claim_once(self):
        for mutation in ('missing', 'duplicate', 'unknown_path'):
            value = deepcopy(self.review)
            if mutation == 'missing':
                value['claims'].pop()
            elif mutation == 'duplicate':
                value['claims'].append(deepcopy(value['claims'][0]))
            else:
                value['claims'][0]['claim_path'] = '/draft/invented'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                narrative.validate_review(value, self.report)

    def test_criteria_are_exact_unique_and_not_silently_filled(self):
        for mutation in ('missing', 'duplicate', 'unknown', 'assessment', 'extra'):
            value = deepcopy(self.review)
            if mutation == 'missing': value['criteria'].pop()
            elif mutation == 'duplicate': value['criteria'][1] = deepcopy(value['criteria'][0])
            elif mutation == 'unknown': value['criteria'][0]['criterion_id'] = 'profitability'
            elif mutation == 'assessment': value['criteria'][0]['assessment'] = 'APPROVED_TO_TRADE'
            else: value['criteria'][0]['score'] = 100
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                narrative.validate_review(value, self.report)

    def test_top_level_unknown_missing_and_unsafe_fields_rejected(self):
        for key, value in [('schema_version', 'v999'), ('rubric_version', 'v999'),
                           ('method', 'MODEL_FACT_CHECK'), ('review_id', '../escape'),
                           ('review_id', 'bad/id'), ('review_id', ''),
                           ('reviewer', ''), ('reviewer', 'Injected\nreviewer'),
                           ('orders', []), ('authorization_enabled', True)]:
            candidate = {**self.review, key: value}
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                narrative.validate_review(candidate, self.report)
        for key in self.review:
            candidate = {name: value for name, value in self.review.items() if name != key}
            with self.subTest(missing=key), self.assertRaises(ValueError):
                narrative.validate_review(candidate, self.report)

    def test_review_clocks_are_aware_and_do_not_backdate_before_source_completion(self):
        for clock in ('2026-10-15T20:00:00', 'bad-time', catalyst.stamp(NOW), None):
            with self.subTest(clock=clock), self.assertRaises(ValueError):
                narrative.validate_review({**self.review, 'reviewed_at': clock}, self.report)

    def test_report_and_packet_bindings_are_required(self):
        for key, value in [('source_report_id', 'sentry-synthesis-' + 'a' * 64),
                           ('source_report_sha256', 'b' * 64), ('packet_sha256', 'c' * 64)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                narrative.validate_review({**self.review, key: value}, self.report)

    def test_unknown_evidence_ids_cannot_be_used_for_criteria_or_claims(self):
        for location in ('criteria', 'claims'):
            value = deepcopy(self.review)
            value[location][0]['evidence_ids' if location == 'criteria' else 'packet_evidence_ids'] = ['ev-' + '0' * 64]
            with self.subTest(location=location), self.assertRaises(ValueError):
                narrative.validate_review(value, self.report)

    def test_duplicate_evidence_and_needed_observations_are_not_independent_support(self):
        for section, key in [('criteria', 'evidence_ids'), ('claims', 'packet_evidence_ids'),
                             ('claims', 'needed_evidence')]:
            value = deepcopy(self.review)
            value[section][0][key] *= 2
            with self.subTest(section=section, key=key), self.assertRaises(ValueError):
                narrative.validate_review(value, self.report)

    def test_claim_cannot_replace_its_original_text_or_add_forecast_fields(self):
        for key, value in [('claim_text', 'Repaired original narrative.'),
                           ('symbol', 'QQQ'), ('expected_return', '10%'),
                           ('confidence', 0.99), ('assessment', 'FALSE')]:
            candidate = deepcopy(self.review)
            candidate['claims'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                narrative.validate_review(candidate, self.report)

    def test_later_user_context_is_labelled_and_cannot_masquerade_as_original_evidence(self):
        value = deepcopy(self.review)
        value['later_context'] = [{'source': 'USER_MESSAGE_AFTER_GENERATION',
                                   'text': 'The user subsequently described rotation out of AI and into staples.'}]
        result = narrative.build_evaluation(self.report, value)
        self.assertEqual(result['later_context'], value['later_context'])
        self.assertEqual(result['packet_sha256'], self.review['packet_sha256'])
        for source in ('PRIMARY_SOURCE', 'ORIGINAL_HEADLINE', 'MODEL_VERIFIED'):
            invalid = deepcopy(value)
            invalid['later_context'][0]['source'] = source
            with self.subTest(source=source), self.assertRaises(ValueError):
                narrative.validate_review(invalid, self.report)

    def test_summary_respects_missing_assessments_and_never_creates_market_verdict(self):
        cases = [('MEETS_RUBRIC', 'MEETS_REVIEW_RUBRIC'), ('PARTIAL', 'MIXED_REVIEW'),
                 ('NOT_ASSESSED', 'REVIEW_INCOMPLETE'), ('NEEDS_WORK', 'NEEDS_REVISION')]
        for assessment, status in cases:
            value = deepcopy(self.review)
            for row in value['criteria']: row['assessment'] = assessment
            evaluation = narrative.build_evaluation(self.report, value)
            with self.subTest(assessment=assessment):
                self.assertEqual(evaluation['summary']['status'], status)
                self.assertTrue(all(flag is False for flag in evaluation['authority'].values()))
                self.assertEqual(evaluation['source_report_id'], self.report['report_id'])
                for forbidden in ('orders', 'allocation', 'expected_return', 'realized_trade_pnl', 'confidence_probability'):
                    self.assertNotIn(forbidden, evaluation)

    def test_saved_evaluation_preserves_original_claims_and_all_source_hashes(self):
        evaluation = narrative.build_evaluation(self.report, self.review)
        for key, original in [('source_report_sha256', self.report),
                              ('packet_sha256', self.report['context']),
                              ('draft_sha256', self.report['draft']),
                              ('challenge_sha256', self.report['challenge']),
                              ('review_sha256', self.review), ('rubric_sha256', narrative.RUBRIC)]:
            self.assertEqual(evaluation[key], sha256_bytes(canonical_json_bytes(original)))
        catalog = {claim['claim_path']: claim for claim in narrative.claim_catalog(self.report)}
        for claim in evaluation['claims']:
            for key, expected in catalog[claim['claim_path']].items():
                self.assertEqual(claim[key], expected)
        detached = deepcopy(evaluation)
        expected = detached.pop('evaluation_sha256')
        self.assertEqual(expected, sha256_bytes(canonical_json_bytes(detached)))

    def test_source_status_identity_original_response_and_authority_are_verified(self):
        for mutation in ('status', 'report_identity', 'draft', 'challenge', 'authority', 'oracle_status'):
            report = deepcopy(self.report)
            if mutation == 'status': report['status'] = 'DRAFT_ONLY'
            elif mutation == 'report_identity': report['report_id'] = 'sentry-synthesis-' + 'a' * 64
            elif mutation == 'draft': report['draft']['overview']['text'] = 'Forged narrative.'
            elif mutation == 'challenge': report['challenge']['reviews'][0]['reason'] = 'Forged dissent.'
            elif mutation == 'authority': report['authority']['execution_enabled'] = True
            else: report['provenance']['oracle']['status'] = 'REJECTED'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                narrative.build_evaluation(report, review_fixture(self.report))

    def test_actual_guard_requires_off_and_the_exact_frozen_protocol(self):
        config = {'runtime_root': '/private/tmp/narrative-off-fixture',
                  'experiment_root': '/private/tmp/narrative-frozen-fixture',
                  'experiment_id': 'frozen-offline-fixture', 'protocol_sha256': 'a' * 64}
        with patch.object(narrative, '_off') as off, patch.object(narrative, '_pinned_view') as pinned:
            narrative._guard(config)
        off.assert_called_once_with(Path(config['runtime_root']))
        pinned.assert_called_once_with(Path(config['experiment_root']), config['experiment_id'], config['protocol_sha256'])
        with patch.object(narrative, '_off', side_effect=ValueError('not OFF')), \
             patch.object(narrative, '_pinned_view') as pinned, self.assertRaises(ValueError):
            narrative._guard(config)
        pinned.assert_not_called()


class SentryNarrativeMechanicalTests(NarrativeFixture):
    def test_keyed_mechanical_observations_retain_symbol_pointer_and_dissent(self):
        report = keyed_report(self.report)
        draft = deepcopy(report['draft'])
        row = draft['themes'][0]['implications_by_symbol']['SPY']
        row['trading'] = 'Materiality remains unknown. Materiality remains unknown.'
        row['investment'] = 'UNSPECIFIED'
        report = recompose(report, draft=draft)
        before = deepcopy(report)
        result = narrative.mechanical_review(report)
        repeated = [row for row in result['findings'] if row['code'] == 'REPEATED_SENTENCE']
        self.assertEqual(repeated[0]['paths'], ['/draft/themes/0/implications_by_symbol/SPY/trading'])
        self.assertEqual(result['unspecified']['investment_count'], 1)
        self.assertEqual(result['coverage']['mentioned_symbols'], ['SPY'])
        self.assertEqual(report['challenge'], before['challenge'])
        self.assertEqual(report, before)

    def test_coverage_is_observed_input_metadata_without_truth_judgments(self):
        result = narrative.mechanical_review(self.report)
        self.assertEqual(result['coverage'], {
            'watchlist': ['SPY', 'QQQ'], 'mentioned_symbols': ['SPY'],
            'unmentioned_symbols': ['QQQ'], 'headline_count': 1,
            'stale_context_count': 2, 'source_count': 1})
        self.assertGreater(len(result['limitations']), 0)
        self.assertEqual(result, narrative.mechanical_review(deepcopy(self.report)))
        self.assertNotIn('truth', result)

    def test_empty_questions_and_unknown_horizons_are_kept_distinct(self):
        result = narrative.mechanical_review(self.report)
        codes = {row['code'] for row in result['findings']}
        self.assertIn('EMPTY_UNRESOLVED_QUESTIONS', codes)
        self.assertEqual(result['unspecified']['horizon_count'], 1)
        self.assertEqual(result['unspecified']['invalidation_count'], 1)
        self.assertNotIn('MISSING_HORIZON_IS_FALSE', codes)

    def test_repeated_sentences_and_title_alternative_are_mechanical_observations(self):
        draft = deepcopy(self.report['draft'])
        draft['themes'][0]['interpretation'] = 'Materiality remains unknown. Materiality remains unknown.'
        draft['themes'][0]['alternative'] = draft['themes'][0]['title']
        result = narrative.mechanical_review(recompose(self.report, draft=draft))
        findings = {row['code']: row for row in result['findings']}
        self.assertIn('REPEATED_SENTENCE', findings)
        self.assertIn('ALTERNATIVE_REPEATS_TITLE', findings)
        self.assertTrue(all(set(row) == {'code', 'paths', 'evidence_ids', 'detail'}
                            for row in result['findings']))

    def test_same_challenge_reason_across_themes_is_visible_without_altering_dissent(self):
        draft = deepcopy(self.report['draft'])
        draft['themes'].append({**deepcopy(draft['themes'][0]), 'theme_id': 'theme-2', 'title': 'Second authored theme'})
        challenge = deepcopy(self.report['challenge'])
        challenge['reviews'].append({**deepcopy(challenge['reviews'][0]), 'theme_id': 'theme-2'})
        report = recompose(self.report, draft=draft, challenge=challenge)
        before = deepcopy(report)
        codes = {row['code'] for row in narrative.mechanical_review(report)['findings']}
        self.assertIn('REPEATED_CHALLENGE_REASON', codes)
        self.assertEqual(report, before)

    def test_evidence_exactly_listed_missing_is_flagged_but_not_broad_keyword_guesses(self):
        headline = next(row for row in self.report['context']['evidence'] if row['kind'] == 'HEADLINE')
        challenge = deepcopy(self.report['challenge'])
        challenge['reviews'][0]['missing_evidence'] = [headline['evidence_id']]
        result = narrative.mechanical_review(recompose(self.report, challenge=challenge))
        findings = [row for row in result['findings'] if row['code'] == 'PRESENT_EVIDENCE_LISTED_AS_MISSING']
        self.assertEqual(len(findings), 1)
        self.assertIn(headline['evidence_id'], findings[0]['evidence_ids'])
        challenge['reviews'][0]['missing_evidence'] = ['Quantified terms and independent confirmation of the agreement.']
        result = narrative.mechanical_review(recompose(self.report, challenge=challenge))
        self.assertNotIn('PRESENT_EVIDENCE_LISTED_AS_MISSING', {row['code'] for row in result['findings']})

    def test_rotation_interpretation_is_not_automatically_declared_false(self):
        draft = deepcopy(self.report['draft'])
        draft['themes'][0].update(title='Market rotation',
            interpretation='AI shares may be unwinding while staples regain attention.',
            alternative='A temporary defensive move may reverse without a durable rotation.')
        result = narrative.mechanical_review(recompose(self.report, draft=draft))
        for finding in result['findings']:
            self.assertNotIn('FALSE', finding['code'])
            self.assertNotIn('rotation is false', finding['detail'].lower())


class SentryNarrativeStorageTests(NarrativeFixture):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.config = {name: str(self.base / name) for name in
                       ('station_root', 'runtime_root', 'experiment_root', 'repo_root', 'historical_root', 'ui_root')}
        self.config['credentials_file'] = str(self.base / 'private/credentials-must-not-be-read.yaml')
        self.guard = self.enterContext(patch.object(narrative, '_guard'))
        self.loader = self.enterContext(patch.object(narrative, 'load_verified_report', return_value=self.report))
        self.enterContext(patch.object(UrlLibTransport, 'request', side_effect=AssertionError('network forbidden')))
        self.enterContext(patch.object(ModelDockClient, 'generate_text', side_effect=AssertionError('inference forbidden')))

    def directory(self):
        return Path(self.config['station_root']) / 'narrative-evaluations' / narrative.evaluation_id(self.review)

    def bytes(self):
        directory = Path(self.config['station_root']) / 'narrative-evaluations'
        return {str(path.relative_to(directory)): path.read_bytes()
                for path in directory.rglob('*') if path.is_file()}

    def test_append_verify_and_identical_retry_are_provider_free_and_immutable(self):
        original = deepcopy(self.report)
        first = narrative.evaluate(self.config, self.review)
        before = self.bytes()
        second = narrative.evaluate(self.config, deepcopy(self.review))
        verified = narrative.verify(self.config, first['evaluation_id'])
        self.assertEqual(first, second)
        self.assertEqual(before, self.bytes())
        self.assertEqual(verified['status'], 'VERIFIED')
        self.assertEqual(verified['provider_calls'], 0)
        self.assertEqual(verified['report'], first)
        self.assertEqual(self.report, original)
        self.assertGreaterEqual(self.guard.call_count, 3)
        self.assertEqual({path.name for path in self.directory().iterdir() if path.is_file()},
                         {'review.json', 'source-report.json', 'evaluation.json'})

    def test_identical_logical_review_identity_with_different_content_conflicts(self):
        original = narrative.evaluate(self.config, self.review)
        before = self.bytes()
        changed = deepcopy(self.review)
        changed['criteria'][0]['rationale'] = 'Different adjudication under the same review identity.'
        with self.assertRaises(Exception): narrative.evaluate(self.config, changed)
        self.assertEqual(self.bytes(), before)
        self.assertEqual(narrative.verify(self.config, original['evaluation_id'])['report'], original)

    def test_a_new_review_id_appends_without_rewriting_prior_evaluation(self):
        original = narrative.evaluate(self.config, self.review)
        before = {path.name: path.read_bytes() for path in self.directory().iterdir() if path.is_file()}
        changed = deepcopy(self.review)
        changed['review_id'] = 'offline-fixture-002'
        changed['criteria'][0]['rationale'] = 'A separately identified later adjudication.'
        later = narrative.evaluate(self.config, changed)
        self.assertNotEqual(original['evaluation_id'], later['evaluation_id'])
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.directory().iterdir() if path.is_file()})
        self.assertEqual(narrative.verify(self.config, original['evaluation_id'])['report'], original)

    def test_missing_partial_publication_is_not_valid_but_identical_retry_recovers(self):
        publisher = narrative._publish_immutable
        published = []

        def interrupt(staging, directory, name, payload):
            publisher(staging, directory, name, payload)
            published.append(name)
            if len(published) == 1: raise OSError('authored interruption after first durable file')

        with patch.object(narrative, '_publish_immutable', side_effect=interrupt), self.assertRaises(OSError):
            narrative.evaluate(self.config, self.review)
        retained = self.bytes()
        self.assertTrue(retained)
        with self.assertRaises(Exception): narrative.verify(self.config, narrative.evaluation_id(self.review))
        result = narrative.evaluate(self.config, self.review)
        self.assertEqual(narrative.verify(self.config, result['evaluation_id'])['status'], 'VERIFIED')
        self.assertTrue(all(self.bytes()[name] == raw for name, raw in retained.items()))

    def test_conflicting_partial_publication_cannot_be_repaired_by_overwrite(self):
        publisher = narrative._publish_immutable
        count = 0

        def interrupt(staging, directory, name, payload):
            nonlocal count
            publisher(staging, directory, name, payload)
            count += 1
            if count == 1: raise OSError('authored interruption')

        with patch.object(narrative, '_publish_immutable', side_effect=interrupt), self.assertRaises(OSError):
            narrative.evaluate(self.config, self.review)
        first = self.bytes()
        changed = deepcopy(self.review)
        changed['reviewer'] = 'Conflicting adjudicator'
        with self.assertRaises(Exception): narrative.evaluate(self.config, changed)
        self.assertEqual(self.bytes(), first)

    def test_source_mutation_after_first_write_prevents_final_publication_and_keeps_original_bytes(self):
        writer = narrative._write
        draft = deepcopy(self.report['draft'])
        draft['themes'][0]['title'] = 'Different source observed during publication'
        replacement = recompose(self.report, draft=draft)

        def replace_source(directory, name, value):
            writer(directory, name, value)
            if name == 'review.json': self.loader.return_value = replacement

        with patch.object(narrative, '_write', side_effect=replace_source), self.assertRaises(ValueError):
            narrative.evaluate(self.config, self.review)
        retained = self.bytes()
        self.assertFalse((self.directory() / 'evaluation.json').exists())
        self.assertEqual((self.directory() / 'review.json').read_bytes(), canonical_json_bytes(self.review))
        self.assertEqual((self.directory() / 'source-report.json').read_bytes(), canonical_json_bytes(self.report))
        with self.assertRaises(Exception): narrative.verify(self.config, narrative.evaluation_id(self.review))
        self.assertEqual(self.bytes(), retained)
        self.loader.return_value = self.report
        result = narrative.evaluate(self.config, self.review)
        self.assertEqual(narrative.verify(self.config, result['evaluation_id'])['status'], 'VERIFIED')
        self.assertTrue(all(self.bytes()[name] == raw for name, raw in retained.items()))

    def test_source_verification_failure_after_first_write_is_retained_and_recoverable(self):
        writer = narrative._write

        def fail_source(directory, name, value):
            writer(directory, name, value)
            if name == 'review.json': self.loader.side_effect = ValueError('authored mid-publication source corruption')

        with patch.object(narrative, '_write', side_effect=fail_source), self.assertRaises(ValueError):
            narrative.evaluate(self.config, self.review)
        retained = self.bytes()
        self.assertFalse((self.directory() / 'evaluation.json').exists())
        self.assertEqual((self.directory() / 'source-report.json').read_bytes(), canonical_json_bytes(self.report))
        with self.assertRaises(ValueError): narrative.verify(self.config, narrative.evaluation_id(self.review))
        self.assertEqual(retained, self.bytes())
        self.loader.side_effect = None
        result = narrative.evaluate(self.config, self.review)
        self.assertEqual(narrative.verify(self.config, result['evaluation_id'])['status'], 'VERIFIED')
        self.assertTrue(all(self.bytes()[name] == raw for name, raw in retained.items()))

    def test_source_mutation_after_final_write_still_prevents_returning_success(self):
        writer = narrative._write
        draft = deepcopy(self.report['draft'])
        draft['themes'][0]['title'] = 'Source changed after final file publication'
        replacement = recompose(self.report, draft=draft)

        def replace_source(directory, name, value):
            writer(directory, name, value)
            if name == 'evaluation.json': self.loader.return_value = replacement

        with patch.object(narrative, '_write', side_effect=replace_source), self.assertRaises(ValueError):
            narrative.evaluate(self.config, self.review)
        retained = self.bytes()
        self.assertTrue((self.directory() / 'evaluation.json').exists())
        self.assertEqual((self.directory() / 'source-report.json').read_bytes(), canonical_json_bytes(self.report))
        with self.assertRaises(Exception): narrative.verify(self.config, narrative.evaluation_id(self.review))
        self.assertEqual(retained, self.bytes())
        self.loader.return_value = self.report
        result = narrative.evaluate(self.config, self.review)
        self.assertEqual(retained, self.bytes())
        self.assertEqual(narrative.verify(self.config, result['evaluation_id'])['status'], 'VERIFIED')

    def test_source_failure_after_final_write_still_prevents_returning_success(self):
        writer = narrative._write

        def fail_source(directory, name, value):
            writer(directory, name, value)
            if name == 'evaluation.json': self.loader.side_effect = ValueError('authored final source verification failure')

        with patch.object(narrative, '_write', side_effect=fail_source), self.assertRaises(ValueError):
            narrative.evaluate(self.config, self.review)
        retained = self.bytes()
        self.assertTrue((self.directory() / 'evaluation.json').exists())
        with self.assertRaises(ValueError): narrative.verify(self.config, narrative.evaluation_id(self.review))
        self.assertEqual(retained, self.bytes())
        self.loader.side_effect = None
        result = narrative.evaluate(self.config, self.review)
        self.assertEqual(retained, self.bytes())
        self.assertEqual(narrative.verify(self.config, result['evaluation_id'])['status'], 'VERIFIED')

    def test_hash_tampering_of_each_retained_file_fails_verification(self):
        for name in ('review.json', 'source-report.json', 'evaluation.json'):
            with self.subTest(name=name):
                result = narrative.evaluate(self.config, self.review)
                path = self.directory() / name
                original = path.read_bytes()
                value = json.loads(original)
                value['forged_field'] = True
                path.chmod(0o600)
                path.write_bytes(canonical_json_bytes(value))
                with self.assertRaises(Exception): narrative.verify(self.config, result['evaluation_id'])
                path.write_bytes(original)
                path.chmod(0o444)

    def test_missing_and_unmatching_review_status_do_not_attach_some_other_brief(self):
        before = narrative.evaluation_status(self.config, self.report)
        self.assertEqual(before['status'], 'NOT_RECORDED')
        self.assertIsNone(before['report'])
        first = narrative.evaluate(self.config, self.review)
        self.assertEqual(narrative.evaluation_status(self.config, self.report)['report'], first)
        draft = deepcopy(self.report['draft'])
        draft['themes'][0]['title'] = 'A different immutable brief'
        other = recompose(self.report, draft=draft)
        different = narrative.evaluation_status(self.config, other)
        self.assertIn(different['status'], {'NO_MATCHING_REVIEW', 'NOT_RECORDED'})
        self.assertIsNone(different['report'])

    def test_corruption_status_fails_closed_and_hides_invalid_assessment(self):
        narrative.evaluate(self.config, self.review)
        path = self.directory() / 'evaluation.json'
        path.chmod(0o600)
        path.write_bytes(b'{}')
        status = narrative.evaluation_status(self.config, self.report)
        self.assertEqual(status['status'], 'UNAVAILABLE')
        self.assertIsNone(status['report'])

    def test_guard_failure_blocks_before_creating_storage(self):
        self.guard.side_effect = ValueError('auto-trading is not OFF')
        with self.assertRaises(ValueError): narrative.evaluate(self.config, self.review)
        self.assertFalse(self.directory().exists())

    def test_source_verification_failure_blocks_before_creating_storage(self):
        self.loader.side_effect = ValueError('tampered source capsule')
        with self.assertRaises(ValueError): narrative.evaluate(self.config, self.review)
        self.assertFalse(self.directory().exists())

    def test_unsafe_capsule_ids_are_refused_before_path_access(self):
        for identity in ('../escape', '/tmp/escape', 'narrative-eval-' + 'A' * 64,
                         'narrative-eval-short', '', None):
            with self.subTest(identity=identity), self.assertRaises(Exception):
                narrative.verify(self.config, identity)

    def test_capsule_symlink_and_file_symlink_are_refused(self):
        target = self.base / 'outside'
        target.mkdir()
        directory = self.directory()
        directory.parent.mkdir(parents=True)
        directory.symlink_to(target, target_is_directory=True)
        with self.assertRaises(Exception): narrative.evaluate(self.config, self.review)
        self.assertEqual(list(target.iterdir()), [])
        directory.unlink()
        result = narrative.evaluate(self.config, self.review)
        path = directory / 'evaluation.json'
        original = path.read_bytes()
        outside = target / 'evaluation.json'
        outside.write_bytes(original)
        path.unlink()
        path.symlink_to(outside)
        with self.assertRaises(Exception): narrative.verify(self.config, result['evaluation_id'])
        self.assertEqual(outside.read_bytes(), original)

    def test_retained_files_with_hardlinks_are_rejected(self):
        result = narrative.evaluate(self.config, self.review)
        path = self.directory() / 'review.json'
        os.link(path, self.base / 'external-hardlink.json')
        with self.assertRaises(Exception): narrative.verify(self.config, result['evaluation_id'])

    def test_storage_does_not_read_credentials_or_write_source_and_runtime(self):
        sentinels = []
        for name in ('runtime_root', 'experiment_root'):
            root = Path(self.config[name]); root.mkdir()
            path = root / 'unchanged.txt'; path.write_text('untouched')
            sentinels.append(path)
        result = narrative.evaluate(self.config, self.review)
        self.assertEqual(narrative.verify(self.config, result['evaluation_id'])['status'], 'VERIFIED')
        self.assertFalse(Path(self.config['credentials_file']).exists())
        for path in sentinels:
            self.assertEqual(path.read_text(), 'untouched')
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_noncanonical_and_oversized_storage_files_fail_closed(self):
        result = narrative.evaluate(self.config, self.review)
        path = self.directory() / 'review.json'
        original = path.read_bytes()
        for payload in (json.dumps(self.review, indent=2).encode(), b' ' * (narrative.MAX_BYTES + 1)):
            path.chmod(0o600); path.write_bytes(payload)
            with self.subTest(size=len(payload)), self.assertRaises(Exception):
                narrative.verify(self.config, result['evaluation_id'])
        path.write_bytes(original); path.chmod(0o444)

    def test_direct_capsule_json_reader_enforces_its_bound_on_valid_canonical_json(self):
        narrative.evaluate(self.config, self.review)
        raw = (self.directory() / 'review.json').read_bytes()
        # Valid JSON and a valid artifact: refusal must come from the requested
        # read bound, rather than incidental syntax or later replay rejection.
        self.assertEqual(json.loads(raw), self.review)
        with patch.object(narrative, 'MAX_BYTES', len(raw) - 1), self.assertRaises(ValueError):
            narrative._json(self.directory(), 'review.json')

    def test_unsafe_staging_entry_is_not_deleted_or_adopted(self):
        result = narrative.evaluate(self.config, self.review)
        path = self.directory() / 'staging' / 'unrecognized.json'
        path.write_text('retain unknown interrupted evidence')
        with self.assertRaises(Exception): narrative.verify(self.config, result['evaluation_id'])
        with self.assertRaises(Exception): narrative.evaluate(self.config, self.review)
        self.assertEqual(path.read_text(), 'retain unknown interrupted evidence')

    def test_known_link_left_after_interrupted_publication_can_verify_and_retry_unchanged(self):
        result = narrative.evaluate(self.config, self.review)
        published = self.directory() / 'review.json'
        interrupted = self.directory() / 'staging' / ('.publish-' + 'a' * 32 + '.tmp')
        os.link(published, interrupted)
        before = self.bytes()
        self.assertEqual(narrative.verify(self.config, result['evaluation_id'])['status'], 'VERIFIED')
        self.assertEqual(narrative.evaluate(self.config, self.review), result)
        self.assertEqual(self.bytes(), before)
        self.assertEqual(published.stat().st_nlink, 2)

    def test_external_hardlink_in_staging_is_refused_and_preserved(self):
        result = narrative.evaluate(self.config, self.review)
        external = self.base / 'external.json'
        external.write_bytes(b'{}')
        linked = self.directory() / 'staging' / ('.publish-' + 'a' * 32 + '.tmp')
        os.link(external, linked)
        with self.assertRaises(Exception): narrative.verify(self.config, result['evaluation_id'])
        self.assertEqual(linked.read_bytes(), b'{}')

    def test_store_capacity_refuses_new_review_without_overwriting_existing_one(self):
        result = narrative.evaluate(self.config, self.review)
        before = self.bytes()
        changed = {**self.review, 'review_id': 'beyond-fixture-capacity'}
        with patch.object(narrative, 'MAX_EVALUATIONS', 1), self.assertRaises(ValueError):
            narrative.evaluate(self.config, changed)
        self.assertEqual(before, self.bytes())
        self.assertEqual(narrative.verify(self.config, result['evaluation_id'])['status'], 'VERIFIED')

    def test_total_byte_capacity_is_preflighted_before_any_capsule_file_publication(self):
        with patch.object(narrative, 'MAX_STORE_BYTES', 1), self.assertRaises(ValueError):
            narrative.evaluate(self.config, self.review)
        self.assertFalse(self.directory().exists())

    def test_future_review_clock_does_not_create_an_evaluation(self):
        value = {**self.review, 'reviewed_at': '2999-01-01T00:00:00Z'}
        with self.assertRaises(ValueError): narrative.evaluate(self.config, value)
        self.assertFalse(self.directory().exists())

    def test_store_must_be_separate_from_source_experiment_runtime_and_credentials(self):
        for key in ('runtime_root', 'experiment_root', 'historical_root', 'ui_root'):
            config = {**self.config, key: str(Path(self.config['station_root']) / 'narrative-evaluations')}
            with self.subTest(key=key), self.assertRaises(Exception):
                narrative.evaluate(config, self.review)
        config = {**self.config, 'credentials_file': str(self.directory() / 'private-key.yaml')}
        with self.assertRaises(Exception): narrative.evaluate(config, self.review)


class SentryNarrativeCliTests(NarrativeFixture):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'review.json'
        self.path.write_bytes(canonical_json_bytes(self.review))
        self.config = {'fixture': True}
        self.loader = self.enterContext(patch('blackpod_build_week.shadow_station.load_config', return_value=self.config))
        self.enterContext(patch.object(UrlLibTransport, 'request', side_effect=AssertionError('network forbidden')))

    def invoke(self, *args):
        stream = StringIO()
        with patch('sys.stdout', stream):
            code = narrative.main([*args, '--config', str(Path(self.tmp.name) / 'station.json')])
        return code, json.loads(stream.getvalue())

    def test_evaluate_cli_returns_safe_summary_without_whole_review_or_source(self):
        evaluation = narrative.build_evaluation(self.report, self.review)
        with patch.object(narrative, 'evaluate', return_value=evaluation) as call:
            code, value = self.invoke('evaluate', '--review', str(self.path))
        self.assertEqual(code, 0)
        self.assertEqual(value['status'], 'RECORDED')
        self.assertEqual(value['provider_calls'], 0)
        self.assertEqual(value['evaluation_id'], evaluation['evaluation_id'])
        call.assert_called_once_with(self.config, self.review)
        self.assertNotIn('claims', value)
        self.assertNotIn('context', value)

    def test_verify_cli_does_not_echo_original_prose(self):
        identity = narrative.evaluation_id(self.review)
        with patch.object(narrative, 'verify', return_value={
                'status': 'VERIFIED', 'evaluation_id': identity, 'provider_calls': 0,
                'report': {'private_fixture': 'original prose'}}):
            code, value = self.invoke('verify', '--evaluation-id', identity)
        self.assertEqual(code, 0)
        self.assertEqual(value, {'status': 'VERIFIED', 'evaluation_id': identity, 'provider_calls': 0})

    def test_cli_failure_uses_closed_status_and_does_not_print_exception_text(self):
        with patch.object(narrative, 'evaluate', side_effect=ValueError('PRIVATE SECRET OR ARTICLE BODY')):
            code, value = self.invoke('evaluate', '--review', str(self.path))
        self.assertEqual(code, 2)
        self.assertEqual(value['status'], 'BLOCKED')
        self.assertEqual(value['provider_calls'], 0)
        self.assertNotIn('PRIVATE', canonical_json_bytes(value).decode())
        self.assertTrue(all(flag is False for flag in value['authority'].values()))

    def test_duplicate_json_keys_and_oversized_input_block_before_evaluation(self):
        for payload in (b'{"review_id":"one","review_id":"two"}', b' ' * (narrative.MAX_BYTES + 1)):
            self.path.write_bytes(payload)
            with self.subTest(size=len(payload)), patch.object(narrative, 'evaluate') as call:
                code, result = self.invoke('evaluate', '--review', str(self.path))
                self.assertEqual(code, 2)
                self.assertEqual(result['status'], 'BLOCKED')
                call.assert_not_called()


class SentryNarrativeServiceIntegrationTests(unittest.TestCase):
    def test_actual_retained_synthesis_verifier_feeds_offline_evaluation_without_new_model_calls(self):
        import test_sentry_synthesis_service as service_fixture
        from blackpod_build_week import sentry_synthesis_service as service
        fixture = service_fixture.SentrySynthesisServiceTests(
            'test_two_roles_real_client_fake_http_and_separate_immutable_dissent')
        fixture.setUp()
        try:
            self.assertEqual(fixture.cycle(), 'CHALLENGED_INTERPRETATION')
            config = {**fixture.config, 'repo_root': str(Path(fixture.tmp.name) / 'repo')}
            directory = fixture.directory()
            report = service.read_report(directory, config)
            review = review_fixture(report)
            before = {str(path.relative_to(directory)): path.read_bytes()
                      for path in directory.rglob('*') if path.is_file()}
            with patch.object(narrative, '_guard'), \
                 patch.object(ModelDockClient, 'generate_text', side_effect=AssertionError('no new inference')), \
                 patch.object(UrlLibTransport, 'request', side_effect=AssertionError('no network')):
                result = narrative.evaluate(config, review)
                self.assertEqual(narrative.verify(config, result['evaluation_id'])['status'], 'VERIFIED')
            self.assertEqual(len(fixture.http.calls), 2)
            self.assertEqual(before, {str(path.relative_to(directory)): path.read_bytes()
                                      for path in directory.rglob('*') if path.is_file()})
            source = next(path for path in directory.rglob('report.json'))
            raw = source.read_bytes()
            source.chmod(0o600)
            source.write_bytes(b'{}')
            with patch.object(narrative, '_guard'), self.assertRaises(Exception):
                narrative.verify(config, result['evaluation_id'])
            source.write_bytes(raw)
            source.chmod(0o444)
        finally:
            fixture.doCleanups()


if __name__ == '__main__':
    unittest.main()
