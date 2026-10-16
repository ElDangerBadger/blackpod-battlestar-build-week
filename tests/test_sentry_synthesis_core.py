"""Offline source replay, bounded packet selection and preserved draft/dissent."""
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week import sentry_catalyst as catalyst
from blackpod_build_week import sentry_synthesis as synthesis
from blackpod_build_week.contracts.sentry_synthesis import ORACLE_SCHEMA_VERSION, CHALLENGE_SCHEMA_VERSION
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from test_sentry_catalyst import NOW, WATCH, packet as capture_packet
from test_sentry_catalyst_audit import changed_packet


class SynthesisCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.config = {key: str(self.base/key) for key in
                       ('repo_root', 'runtime_root', 'experiment_root', 'historical_root', 'ui_root')}
        self.config['station_root'] = str(self.base/'station')
        self.config['credentials_file'] = str(self.base/'private/keys.yaml')
        self.store = catalyst.CatalystStore(self.base/'station/catalyst/evidence-store')

    def build(self, at=NOW):
        records, verification = self.store.verified_records()
        return synthesis.build_packet(records, verification, at)

    def headlines(self, packet):
        return [row for row in packet['evidence'] if row['kind'] == 'HEADLINE']

    def test_packet_is_deterministic_content_addressed_and_does_not_write_source(self):
        self.store.append(*capture_packet())
        before = {str(p.relative_to(self.store.root)): p.read_bytes()
                  for p in self.store.root.rglob('*') if p.is_file()}
        first, second = self.build(), self.build()
        self.assertEqual(first, second)
        original = deepcopy(first); identity = original.pop('context_id')
        self.assertEqual(identity, 'sentry-context-' + sha256_bytes(canonical_json_bytes(original)))
        for evidence in first['evidence']:
            original = deepcopy(evidence); identity = original.pop('evidence_id')
            self.assertEqual(identity, 'ev-' + sha256_bytes(canonical_json_bytes(original)))
        after = {str(p.relative_to(self.store.root)): p.read_bytes()
                 for p in self.store.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_headline_has_exact_source_identity_revision_and_original_clocks(self):
        projection, blobs = capture_packet()
        receipt = self.store.append(projection, blobs)
        evidence = self.headlines(self.build())[0]
        article = projection['articles'][0]
        for field, value in article.items(): self.assertEqual(evidence['data'][field], value)
        self.assertEqual(evidence['binding'], {'capture_id': receipt['capture_id'], 'captured_at': catalyst.stamp(NOW),
                         'news_sha256': sha256_bytes(blobs['news']), 'provider_id': article['provider_id'],
                         'revision_sha256': article['revision_sha256']})
        self.assertEqual(evidence['data']['first_seen_at'], catalyst.stamp(NOW))
        self.assertEqual(evidence['data']['revision_first_seen_at'], catalyst.stamp(NOW))
        self.assertEqual(evidence['data']['content_level'], 'HEADLINE_ONLY')

    def test_new_revision_preserves_first_seen_and_original_retained_capture(self):
        first, blobs = capture_packet()
        self.store.append(first, blobs)
        original_bytes = (self.store.root/'entries/00000001.json').read_bytes()
        later = NOW + timedelta(minutes=5)
        def revise(news, snapshots):
            news['news'][0].update(headline='Updated agreement terms', created_at=first['articles'][0]['published_at'],
                                   updated_at=catalyst.stamp(later-timedelta(seconds=10)))
        second, next_blobs = changed_packet(later, change=revise)
        self.store.append(second, next_blobs)
        evidence = self.headlines(self.build(later))[0]
        self.assertEqual(evidence['data']['headline'], 'Updated agreement terms')
        self.assertEqual(evidence['data']['first_seen_at'], catalyst.stamp(NOW))
        self.assertEqual(evidence['data']['revision_first_seen_at'], catalyst.stamp(later))
        self.assertEqual(evidence['binding']['revision_sha256'], second['articles'][0]['revision_sha256'])
        self.assertEqual((self.store.root/'entries/00000001.json').read_bytes(), original_bytes)
        self.assertEqual(len(self.headlines(self.build(later))), 1)

    def test_repeated_observation_is_not_a_second_headline_or_new_signal_signature(self):
        projection, blobs = capture_packet()
        self.store.append(projection, blobs)
        first = self.build()
        later = NOW + timedelta(minutes=5)
        repeated = catalyst.project(blobs['news'], blobs['snapshots'], WATCH, catalyst.stamp(later))
        self.store.append(repeated, blobs)
        second = self.build(later)
        self.assertEqual(len(self.headlines(second)), 1)
        self.assertEqual(second['evidence_signature'], first['evidence_signature'])
        self.assertEqual(second['quality']['source_count'], 1)
        self.assertIs(second['quality']['independent_sources_verified'], False)

    def test_article_bodies_are_not_promoted_and_holdings_are_unavailable(self):
        def body(news, snapshots):
            news['news'][0].update(content='PRIVATE ARTICLE BODY MUST NOT ENTER MODEL CATALOG', summary='UNREAD SUMMARY')
        self.store.append(*changed_packet(change=body))
        packet = self.build()
        raw = canonical_json_bytes(packet)
        self.assertNotIn(b'PRIVATE ARTICLE BODY', raw)
        self.assertNotIn(b'UNREAD SUMMARY', raw)
        self.assertEqual(packet['portfolio'], {'status': 'UNAVAILABLE_NO_VERIFIED_HOLDINGS'})
        self.assertIs(packet['quality']['holdings_available'], False)
        self.assertTrue(all(value is False for value in packet['authority'].values()))
        for field in ('orders', 'recommendation', 'position_size', 'expected_return', 'realized_trade_pnl'):
            self.assertNotIn(field, packet)

    def test_attention_duplicates_by_exact_url_or_normalized_headline_do_not_corroborate(self):
        for method in ('url', 'headline'):
            def duplicates(news, snapshots):
                first = news['news'][0]
                if method == 'url':
                    news['news'] += [{**first, 'id': 124, 'headline': 'Different title, same URL'},
                                     {**first, 'id': 125, 'headline': 'Third title, same URL', 'source': 'second-source'}]
                else:
                    news['news'] += [{**first, 'id': 124, 'url': 'https://example.com/another',
                                      'headline': '  COMPANY   ANNOUNCES An Agreement  ', 'source': 'second-source'},
                                     {**first, 'id': 125, 'url': 'https://example.com/third'}]
            store = catalyst.CatalystStore(self.base/method)
            store.append(*changed_packet(change=duplicates))
            records, verification = store.verified_records()
            packet = synthesis.build_packet(records, verification, NOW)
            with self.subTest(method=method):
                self.assertEqual(packet['selection']['eligible_article_count'], 3)
                self.assertEqual(packet['selection']['attention_duplicate_count'], 2)
                self.assertEqual(len(self.headlines(packet)), 1)
                self.assertIs(packet['quality']['independent_sources_verified'], False)

    def test_twenty_headline_bound_preserves_available_watchlist_coverage_before_recent_fill(self):
        def many(news, snapshots):
            template = news['news'][0]
            news['news'] = [{**template, 'id': i+1000, 'headline': f'Distinct headline {i}',
                            'url': f'https://example.com/story-{i}', 'symbols': ['QQQ'] if i == 29 else ['SPY'],
                            'updated_at': catalyst.stamp(NOW-timedelta(minutes=i+1))} for i in range(30)]
        self.store.append(*changed_packet(change=many))
        packet = self.build()
        self.assertEqual(packet['selection']['selected_headline_count'], 20)
        self.assertEqual(packet['selection']['omitted_headline_count'], 10)
        self.assertEqual(packet['selection']['attention_duplicate_count'], 0)
        selected = self.headlines(packet)
        self.assertEqual(len(selected), 20)
        self.assertTrue(any(row['symbols'] == ['QQQ'] for row in selected))
        self.assertTrue(any(row['symbols'] == ['SPY'] for row in selected))

    def test_selection_uses_recent_updates_not_fabricated_publication_freshness(self):
        def old_and_recent(news, snapshots):
            template = news['news'][0]
            old = catalyst.stamp(NOW-timedelta(hours=30))
            news['news'] = [{**template, 'id': 200, 'headline': 'Old item', 'url': 'https://example.com/old',
                            'created_at': old, 'updated_at': catalyst.stamp(NOW-timedelta(hours=24, seconds=1))},
                           {**template, 'id': 201, 'headline': 'Old publication recently updated',
                            'url': 'https://example.com/update', 'created_at': old,
                            'updated_at': catalyst.stamp(NOW-timedelta(minutes=2))},
                           {**template, 'id': 202, 'headline': 'Exactly at 24 hour boundary',
                            'url': 'https://example.com/boundary', 'created_at': old,
                            'updated_at': catalyst.stamp(NOW-timedelta(hours=24))}]
        self.store.append(*changed_packet(change=old_and_recent))
        packet = self.build()
        self.assertEqual({r['data']['provider_id'] for r in self.headlines(packet)}, {'201', '202'})
        updated = next(row for row in self.headlines(packet) if row['data']['provider_id'] == '201')
        self.assertEqual(updated['data']['published_at'], catalyst.stamp(NOW-timedelta(hours=30)))

    def test_small_future_article_clocks_are_excluded_not_backdated(self):
        def future(news, snapshots):
            news['news'][0].update(created_at=catalyst.stamp(NOW+timedelta(seconds=2)),
                                   updated_at=catalyst.stamp(NOW+timedelta(seconds=2)))
        self.store.append(*changed_packet(change=future))
        packet = self.build()
        self.assertEqual(self.headlines(packet), [])
        self.assertEqual(packet['selection']['excluded_future_article_count'], 1)
        self.assertEqual(packet['selection']['selected_headline_count'], 0)
        self.assertEqual(len(packet['evidence']), 3)  # Two prices plus quality, not invented news.

    def test_latest_watchlist_is_exact_and_old_scope_does_not_leak_in(self):
        self.store.append(*capture_packet())
        later = NOW + timedelta(minutes=5)
        self.store.append(*changed_packet(later, selected=['QQQ']))
        packet = self.build(later)
        self.assertEqual(packet['watchlist'], ['QQQ'])
        self.assertEqual(self.headlines(packet), [])
        self.assertEqual([r['symbols'] for r in packet['evidence'] if r['kind'] == 'PRICE_CONTEXT'], [['QQQ']])

    def test_context_freshness_at_packet_is_separate_from_original_observation(self):
        self.store.append(*capture_packet())
        packet = self.build(NOW+timedelta(hours=1))
        contexts = [row for row in packet['evidence'] if row['kind'] == 'PRICE_CONTEXT']
        self.assertEqual(len(contexts), 2)
        for row in contexts:
            self.assertEqual(row['data']['status'], 'OBSERVED')
            self.assertEqual(row['data']['freshness_at_packet'], 'STALE')
            self.assertEqual(row['data']['age_at_packet_seconds'], 3660)
            self.assertEqual(row['data']['price_change_basis'], 'MINUTE_CLOSE_VS_PREVIOUS_DAILY_CLOSE_NOT_NEWS_RESPONSE')
        self.assertEqual(packet['quality']['stale_context_count'], 2)
        self.assertEqual(packet['quality']['fresh_context_count'], 0)
        self.assertIs(packet['quality']['post_headline_reaction_available'], False)

    def test_missing_and_future_price_contexts_are_explicit_and_not_repaired(self):
        def prices(news, snapshots):
            del snapshots['SPY']
            snapshots['QQQ']['minuteBar']['t'] = catalyst.stamp(NOW+timedelta(seconds=2))
            news['next_page_token'] = 'more-news'
        self.store.append(*changed_packet(change=prices))
        packet = self.build()
        contexts = {r['symbols'][0]: r['data'] for r in packet['evidence'] if r['kind'] == 'PRICE_CONTEXT'}
        self.assertEqual(contexts['SPY']['freshness_at_packet'], 'UNAVAILABLE')
        self.assertIsNone(contexts['SPY']['age_at_packet_seconds'])
        self.assertNotIn('price', contexts['SPY'])
        self.assertEqual(contexts['QQQ']['freshness_at_packet'], 'FUTURE_TIMESTAMP')
        self.assertEqual(packet['quality']['future_context_count'], 1)
        self.assertEqual(packet['quality']['unavailable_context_count'], 1)
        self.assertIs(packet['quality']['news_truncated'], True)
        self.assertIsNone(packet['quality']['overall_news_coverage_fraction'])

    def test_quality_is_bound_to_same_prefix_audit(self):
        self.store.append(*capture_packet())
        records, verification = self.store.verified_records()
        packet = self.build()
        audit = synthesis.feed_audit(records, verification, NOW)
        evidence = next(row for row in packet['evidence'] if row['kind'] == 'FEED_QUALITY')
        self.assertEqual(evidence['binding']['audit_report_id'], audit['report_id'])
        self.assertEqual(evidence['binding']['audit_report_sha256'], sha256_bytes(canonical_json_bytes(audit)))
        self.assertEqual(packet['source']['head_sha256'], verification['head_sha256'])
        self.assertEqual(packet['quality']['capture_count'], verification['capture_count'])

    def test_original_packet_replays_after_later_captures_append(self):
        self.store.append(*capture_packet())
        original = self.build()
        before = canonical_json_bytes(original)
        self.store.append(*capture_packet(at=NOW+timedelta(minutes=5)))
        verified = synthesis.verify_packet(original, self.config)
        self.assertEqual(verified, original)
        self.assertEqual(canonical_json_bytes(verified), before)
        self.assertEqual(self.store.verify()['capture_count'], 2)

    def test_modified_context_scope_head_count_or_claim_cannot_replay(self):
        self.store.append(*capture_packet())
        original = self.build()
        for mutation in ('scope', 'head', 'count', 'context_id', 'headline', 'holdings', 'clock'):
            packet = deepcopy(original)
            if mutation == 'scope': packet['watchlist'] = ['SPY']
            if mutation == 'head': packet['source']['head_sha256'] = '0'*64
            if mutation == 'count': packet['source']['capture_count'] = True
            if mutation == 'context_id': packet['context_id'] = 'forged'
            if mutation == 'headline': self.headlines(packet)[0]['data']['headline'] = 'Invented claim'
            if mutation == 'holdings': packet['portfolio']['status'] = 'HOLDINGS_VERIFIED'
            if mutation == 'clock': packet['as_of'] = catalyst.stamp(NOW-timedelta(seconds=1))
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): synthesis.verify_packet(packet, self.config)

    def test_source_tampering_blocks_current_and_original_packet(self):
        self.store.append(*capture_packet())
        original = self.build()
        path = next((self.store.root/'evidence').iterdir())
        path.chmod(0o600); path.write_bytes(b'{}')
        with self.assertRaises(ValueError): synthesis.current_packet(self.config, NOW)
        with self.assertRaises(ValueError): synthesis.verify_packet(original, self.config)

    def test_empty_naive_and_pre_source_clocks_are_refused(self):
        with self.assertRaises(ValueError): synthesis.build_packet([], {}, NOW)
        self.store.append(*capture_packet())
        records, verification = self.store.verified_records()
        for at in (NOW.replace(tzinfo=None), NOW-timedelta(seconds=1)):
            with self.subTest(at=at), self.assertRaises(ValueError): synthesis.build_packet(records, verification, at)

    def test_catalog_build_and_verify_never_read_credentials_or_call_collectors(self):
        self.store.append(*capture_packet())
        with patch('blackpod_build_week.sentry_catalyst_service.parse_credentials', side_effect=AssertionError('credentials forbidden')), \
             patch('blackpod_build_week.sentry_catalyst_service.market_get', side_effect=AssertionError('provider forbidden')), \
             patch('blackpod_build_week.sentry_catalyst_service.cycle', side_effect=AssertionError('collector forbidden')):
            packet = synthesis.current_packet(self.config, NOW)
            self.assertEqual(synthesis.verify_packet(packet, self.config), packet)

    def model_results(self, packet):
        evidence = self.headlines(packet)[0]['evidence_id']
        draft = {'schema_version': ORACLE_SCHEMA_VERSION,
                 'overview': {'text': 'This selected headline permits only tentative interpretation.', 'evidence_ids': [evidence]},
                 'themes': [{'theme_id': 'theme-1', 'title': 'Agreement headline',
                             'interpretation': 'Possible implications remain uncertain.', 'evidence_ids': [evidence],
                             'implications': [{'symbol': 'SPY', 'linkage': 'DIRECT_MENTION',
                                               'trading': 'Unknown short-term relevance.', 'investment': 'Unknown economic materiality.'}],
                             'alternative': 'The news may be economically immaterial.', 'proposed_invalidation': {'status': 'UNSPECIFIED', 'text': ''},
                             'proposed_review_horizon': 'UNSPECIFIED'}], 'unresolved_questions': []}
        challenge = {'schema_version': CHALLENGE_SCHEMA_VERSION,
                     'draft_sha256': sha256_bytes(canonical_json_bytes(draft)),
                     'reviews': [{'theme_id': 'theme-1', 'status': 'CONTESTED',
                                  'reason': 'A headline does not establish business effects.', 'evidence_ids': [evidence],
                                  'alternative': 'The announcement may not change expectations.', 'missing_evidence': ['Primary terms']}],
                     'overall_limitations': ['Same retained source, not independent corroboration.']}
        return {'status': 'ACCEPTED', 'response': draft}, {'status': 'ACCEPTED', 'response': challenge}

    def test_composed_report_preserves_original_draft_and_dissent_without_authority(self):
        self.store.append(*capture_packet())
        packet = self.build()
        oracle, challenge = self.model_results(packet)
        before = deepcopy((packet, oracle, challenge))
        report = synthesis.compose_report(packet, oracle, challenge, catalyst.stamp(NOW+timedelta(seconds=30)))
        self.assertEqual((packet, oracle, challenge), before)
        self.assertEqual(report['draft'], oracle['response'])
        self.assertEqual(report['challenge'], challenge['response'])
        self.assertEqual(report['challenge']['reviews'][0]['status'], 'CONTESTED')
        self.assertEqual(report['status'], 'CHALLENGED_INTERPRETATION')
        self.assertEqual(report['review_independence'], {'separate_review_pass': True,
                         'independent_model_verified': False, 'independent_sources_verified': False})
        self.assertTrue(all(value is False for value in report['authority'].values()))
        original = deepcopy(report); identity = original.pop('report_id')
        self.assertEqual(identity, 'sentry-synthesis-'+sha256_bytes(canonical_json_bytes(original)))

    def test_missing_challenge_remains_draft_only_and_failed_oracle_cannot_promote_review(self):
        self.store.append(*capture_packet())
        packet = self.build(); oracle, challenge = self.model_results(packet)
        report = synthesis.compose_report(packet, oracle, {'status': 'VALIDATION_FAILED'}, catalyst.stamp(NOW))
        self.assertEqual(report['status'], 'DRAFT_ONLY')
        self.assertIsNone(report['challenge'])
        self.assertIs(report['review_independence']['separate_review_pass'], False)
        report = synthesis.compose_report(packet, {'status': 'TIMED_OUT'}, challenge, catalyst.stamp(NOW))
        self.assertEqual(report['status'], 'TIMED_OUT')
        self.assertIsNone(report['draft']); self.assertIsNone(report['challenge'])

    def test_explicit_validation_link_is_strict_detached_and_hash_bound(self):
        self.store.append(*capture_packet())
        packet = self.build(); oracle, challenge = self.model_results(packet)
        at = catalyst.stamp(NOW+timedelta(hours=2))
        ordinary = synthesis.compose_report(packet, oracle, challenge, at)
        linkage = {'purpose': 'EXPLICIT_V2_VALIDATION',
                   'parent_report_id': 'sentry-synthesis-'+'a'*64,
                   'parent_report_sha256': 'b'*64,
                   'transport_schema_version': 'blackpod.sentry_synthesis_transport.v2'}
        original = deepcopy(linkage)
        report = synthesis.compose_report(packet, oracle, challenge, at, validation=linkage)
        self.assertEqual(report['context'], packet)
        self.assertEqual(report['context']['as_of'], catalyst.stamp(NOW))
        self.assertEqual(report['validation'], original)
        self.assertNotEqual(report['report_id'], ordinary['report_id'])
        self.assertNotIn('validation', ordinary)
        payload = deepcopy(report); identity = payload.pop('report_id')
        self.assertEqual(identity, 'sentry-synthesis-'+sha256_bytes(canonical_json_bytes(payload)))
        linkage['parent_report_sha256'] = 'c'*64
        self.assertEqual(report['validation'], original)
        for key, value in [('purpose', 'RETRY'), ('parent_report_id', 'bad'),
                           ('parent_report_sha256', 'B'*64),
                           ('transport_schema_version', 'blackpod.sentry_synthesis_transport.v1'),
                           ('extra', True)]:
            invalid = {**original, key: value}
            with self.subTest(key=key), self.assertRaises(ValueError):
                synthesis.compose_report(packet, oracle, challenge, at, validation=invalid)

    def test_mismatched_or_malformed_accepted_challenge_is_not_silently_dropped(self):
        self.store.append(*capture_packet())
        packet = self.build(); oracle, challenge = self.model_results(packet)
        challenge['response']['draft_sha256'] = '0'*64
        with self.assertRaises(ValueError): synthesis.compose_report(packet, oracle, challenge, catalyst.stamp(NOW))

    def test_deadline_validation_requires_manual_scope_and_v3_link(self):
        self.store.append(*capture_packet())
        packet = self.build(); oracle, challenge = self.model_results(packet)
        metadata = {'purpose': 'EXPLICIT_DEADLINE_VALIDATION',
            'parent_report_id': 'sentry-synthesis-'+'a'*64, 'parent_report_sha256': 'b'*64,
            'transport_schema_version': 'blackpod.sentry_synthesis_transport.v3',
            'scope': 'MANUAL_RETAINED_EVIDENCE'}
        report = synthesis.compose_report(packet, oracle, challenge, catalyst.stamp(NOW+timedelta(hours=3)), validation=metadata)
        self.assertEqual(report['validation'], metadata)
        self.assertEqual(report['context']['as_of'], catalyst.stamp(NOW))
        self.assertTrue(all(value is False for value in report['authority'].values()))
        for key, value in [('scope','AUTOMATIC'), ('transport_schema_version','blackpod.sentry_synthesis_transport.v2')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                synthesis.compose_report(packet, oracle, challenge, catalyst.stamp(NOW), validation={**metadata,key:value})
        with self.assertRaises(ValueError):
            synthesis.compose_report(packet, oracle, challenge, catalyst.stamp(NOW),
                validation={key:value for key,value in metadata.items() if key!='scope'})

    def test_contract_validation_requires_manual_scope_and_v8_link(self):
        self.store.append(*capture_packet())
        packet=self.build();oracle,challenge=self.model_results(packet)
        metadata={'purpose':'EXPLICIT_CONTRACT_VALIDATION',
            'parent_report_id':'sentry-synthesis-'+'a'*64,'parent_report_sha256':'b'*64,
            'transport_schema_version':'blackpod.sentry_synthesis_transport.v8',
            'scope':'MANUAL_RETAINED_EVIDENCE'}
        report=synthesis.compose_report(packet,oracle,challenge,catalyst.stamp(NOW),validation=metadata)
        self.assertEqual(report['context'],packet)
        self.assertEqual(report['validation'],metadata)
        for key,value in [('scope','AUTOMATIC'),('transport_schema_version','blackpod.sentry_synthesis_transport.v7')]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                synthesis.compose_report(packet,oracle,challenge,catalyst.stamp(NOW),validation={**metadata,key:value})

    def test_output_budget_validation_requires_manual_scope_and_v7_link(self):
        self.store.append(*capture_packet())
        packet=self.build();oracle,challenge=self.model_results(packet)
        metadata={'purpose':'EXPLICIT_OUTPUT_BUDGET_VALIDATION',
            'parent_report_id':'sentry-synthesis-'+'a'*64,'parent_report_sha256':'b'*64,
            'transport_schema_version':'blackpod.sentry_synthesis_transport.v7',
            'scope':'MANUAL_RETAINED_EVIDENCE'}
        report=synthesis.compose_report(packet,oracle,challenge,catalyst.stamp(NOW),validation=metadata)
        self.assertEqual(report['context'],packet)
        self.assertEqual(report['validation'],metadata)
        for key,value in [('scope','AUTOMATIC'),('transport_schema_version','blackpod.sentry_synthesis_transport.v6')]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                synthesis.compose_report(packet,oracle,challenge,catalyst.stamp(NOW),validation={**metadata,key:value})

    def test_model_selection_validation_requires_manual_scope_and_v6_link(self):
        self.store.append(*capture_packet())
        packet=self.build();oracle,challenge=self.model_results(packet)
        metadata={'purpose':'EXPLICIT_MODEL_SELECTION_VALIDATION',
            'parent_report_id':'sentry-synthesis-'+'a'*64,'parent_report_sha256':'b'*64,
            'transport_schema_version':'blackpod.sentry_synthesis_transport.v6',
            'scope':'MANUAL_RETAINED_EVIDENCE'}
        report=synthesis.compose_report(packet,oracle,challenge,catalyst.stamp(NOW),validation=metadata)
        self.assertEqual(report['context'],packet)
        self.assertEqual(report['validation'],metadata)
        for key,value in [('scope','AUTOMATIC'),('transport_schema_version','blackpod.sentry_synthesis_transport.v5')]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                synthesis.compose_report(packet,oracle,challenge,catalyst.stamp(NOW),validation={**metadata,key:value})

    def test_runtime_diagnostic_requires_manual_scope_and_v5_link(self):
        self.store.append(*capture_packet())
        packet=self.build();oracle,challenge=self.model_results(packet)
        metadata={'purpose':'EXPLICIT_RUNTIME_DIAGNOSTIC',
            'parent_report_id':'sentry-synthesis-'+'a'*64,'parent_report_sha256':'b'*64,
            'transport_schema_version':'blackpod.sentry_synthesis_transport.v5',
            'scope':'MANUAL_RETAINED_EVIDENCE'}
        report=synthesis.compose_report(packet,oracle,challenge,catalyst.stamp(NOW),validation=metadata)
        self.assertEqual(report['context'],packet)
        self.assertEqual(report['validation'],metadata)
        for key,value in [('scope','AUTOMATIC'),('transport_schema_version','blackpod.sentry_synthesis_transport.v4')]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                synthesis.compose_report(packet,oracle,challenge,catalyst.stamp(NOW),validation={**metadata,key:value})

    def test_error_code_diagnostic_requires_manual_scope_and_v4_link(self):
        self.store.append(*capture_packet())
        packet = self.build(); oracle, challenge = self.model_results(packet)
        metadata = {'purpose':'EXPLICIT_ERROR_CODE_DIAGNOSTIC',
            'parent_report_id':'sentry-synthesis-'+'a'*64,'parent_report_sha256':'b'*64,
            'transport_schema_version':'blackpod.sentry_synthesis_transport.v4',
            'scope':'MANUAL_RETAINED_EVIDENCE'}
        original = deepcopy(metadata)
        report = synthesis.compose_report(packet, oracle, challenge, catalyst.stamp(NOW+timedelta(hours=4)), validation=metadata)
        self.assertEqual(report['validation'], original)
        self.assertEqual(report['context'], packet)
        self.assertTrue(all(value is False for value in report['authority'].values()))
        metadata['parent_report_sha256']='c'*64
        self.assertEqual(report['validation'], original)
        for key,value in [('scope','AUTOMATIC'),('transport_schema_version','blackpod.sentry_synthesis_transport.v3')]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                synthesis.compose_report(packet,oracle,challenge,catalyst.stamp(NOW),validation={**original,key:value})


if __name__ == '__main__':
    unittest.main()
