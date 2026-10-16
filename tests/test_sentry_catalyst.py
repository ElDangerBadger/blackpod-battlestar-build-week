"""Deterministic catalyst observations and immutable retained evidence; no network."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week import sentry_catalyst as m
from blackpod_build_week import sentry_catalyst_service as service
from blackpod_build_week import sentry_catalyst_capture as capture
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.paper_account_probe import PaperCredentials
from blackpod_build_week.shadow_station import atomic_state

NOW = datetime(2026, 10, 15, 18, tzinfo=timezone.utc)
WATCH = ['SPY', 'QQQ']

def fixture(at=NOW, headline='Company announces an agreement', identity=123):
    minute = m.stamp(at - timedelta(minutes=1))
    day = m.stamp(at.replace(hour=4, minute=0, second=0))
    previous = m.stamp((at - timedelta(days=1)).replace(hour=4, minute=0, second=0))
    def bar(t, close=100):
        return {'t': t, 'o': 100, 'h': 102, 'l': 98, 'c': close, 'v': 1234}
    news = {'news': [{'id': identity, 'headline': headline, 'source': 'fixture-source',
            'url': 'https://example.com/story', 'created_at': m.stamp(at - timedelta(hours=1)),
            'updated_at': m.stamp(at - timedelta(minutes=30)), 'symbols': ['SPY', 'OTHER']}], 'next_page_token': None}
    snapshots = {s: {'minuteBar': bar(minute, 101), 'dailyBar': bar(day), 'prevDailyBar': bar(previous)} for s in WATCH}
    return news, snapshots


def packet(at=NOW, *, feed='iex', **kwargs):
    news, snaps = fixture(at=at, **kwargs)
    raws = {'news': canonical_json_bytes(news), 'snapshots': canonical_json_bytes(snaps)}
    query = {'symbols': ','.join(WATCH), 'start': m.stamp(at-timedelta(hours=24)), 'end': m.stamp(at),
             'limit': 50, 'sort': 'desc', 'include_content': 'false'}
    for kind in ('news', 'snapshots'):
        receipt = {'schema_version': ('blackpod.sentry_catalyst_get.v2'
                   if kind == 'snapshots' and feed != 'iex' else 'blackpod.sentry_catalyst_get.v1'),
                   'method': 'GET', 'url': capture.URLS[kind],
                   'query': query if kind == 'news' else {'symbols': ','.join(WATCH), 'feed': feed},
                   'captured_at': m.stamp(at), 'status': 200, 'body_sha256': sha256_bytes(raws[kind]), 'size_bytes': len(raws[kind])}
        raws[kind + '_receipt'] = canonical_json_bytes(receipt)
    return m.project(raws['news'], raws['snapshots'], WATCH, m.stamp(at), feed=feed), raws


class ProjectionTests(unittest.TestCase):
    def project(self, news, snaps):
        return m.project(canonical_json_bytes(news), canonical_json_bytes(snaps), WATCH, m.stamp(NOW))

    def test_no_authority_and_exact_price_volume_context(self):
        result, _ = packet()
        self.assertEqual(result['authority'], 'OBSERVATION_ONLY')
        self.assertEqual(result['contexts'][0]['change_from_previous_close_pct'], '1.00')
        self.assertEqual(result['contexts'][0]['day_volume'], '1234')
        self.assertEqual(result['articles'][0]['symbols'], ['SPY'])
        self.assertNotIn('sentiment', result['articles'][0])
        self.assertNotIn('recommendation', result)

    def test_arithmetic_independent_of_callers_decimal_context(self):
        from decimal import localcontext
        news, snapshots = fixture()
        snapshots['SPY']['prevDailyBar'].update(o=3,h=3,l=3,c=3)
        expected = self.project(news,snapshots)
        with localcontext() as context:
            context.prec = 6
            self.assertEqual(self.project(news,snapshots),expected)

    def test_watchlist_bounds_and_injection_rejected(self):
        for value in ([], ['SPY'] * 2, ['SPY&feed=sip'], ['spy'], ['SPY'] + [f'A{i}' for i in range(10)]):
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                m.symbols(value)

    def test_missing_invalid_symbol_bar_is_local_unavailable(self):
        news, snaps = fixture()
        snaps['SPY']['minuteBar']['c'] = -1
        result = self.project(news, snaps)
        self.assertEqual(result['contexts'][0]['status'], 'UNAVAILABLE')
        self.assertEqual(result['contexts'][1]['status'], 'OBSERVED')

    def test_future_and_inconsistent_bars_are_not_repaired(self):
        for key, value in [('t', m.stamp(NOW + timedelta(hours=1))), ('v', -3), ('h', 1), ('c', True)]:
            news, snaps = fixture()
            snaps['SPY']['minuteBar'][key] = value
            self.assertEqual(self.project(news, snaps)['contexts'][0]['status'], 'UNAVAILABLE')

    def test_old_prices_have_explicit_stale_status(self):
        news, snaps = fixture()
        snaps['SPY']['minuteBar']['t'] = m.stamp(NOW - timedelta(hours=1))
        self.assertEqual(self.project(news, snaps)['contexts'][0]['status'], 'STALE')

    def test_duplicate_news_and_future_news_rejected(self):
        news, snaps = fixture()
        news['news'].append(deepcopy(news['news'][0]))
        with self.assertRaises(ValueError): self.project(news, snaps)
        news, snaps = fixture()
        news['news'][0]['updated_at'] = m.stamp(NOW + timedelta(hours=1))
        with self.assertRaises(ValueError): self.project(news, snaps)

    def test_source_scheme_and_control_text_rejected(self):
        for field, value in [('url', 'javascript:alert(1)'), ('url', 'https://a:b@example.com'), ('headline', 'hello\nworld')]:
            news, snaps = fixture()
            news['news'][0][field] = value
            with self.assertRaises(ValueError): self.project(news, snaps)

    def test_empty_news_not_failure_and_pagination_is_explicit(self):
        news, snaps = fixture()
        news['news'] = []
        news['next_page_token'] = 'more'
        result = self.project(news, snaps)
        self.assertEqual(result['articles'], [])
        self.assertTrue(result['news_truncated'])

    def test_unknown_snapshot_symbol_rejected(self):
        news, snaps = fixture()
        snaps['OTHER'] = snaps['SPY']
        with self.assertRaises(ValueError): self.project(news, snaps)

    def test_strict_numeric_json_no_nonfinite_or_duplicate_keys(self):
        _, snaps = fixture()
        for raw in (b'{"news":[],"news":[]}', b'{"news":[NaN]}'):
            with self.assertRaises(ValueError): m.project(raw, canonical_json_bytes(snaps), WATCH, m.stamp(NOW))

    def test_consolidated_projection_preserves_volume_and_names_scope(self):
        for feed, delay in [('sip', 0), ('delayed_sip', 900)]:
            with self.subTest(feed=feed):
                result, _ = packet(feed=feed)
                self.assertEqual(result['schema_version'], m.CONSOLIDATED_VERSION)
                self.assertEqual(result['market_feed'], feed)
                self.assertEqual(result['feed_delay_seconds'], delay)
                self.assertEqual(result['contexts'][0]['day_volume'], '1234')
                self.assertEqual(result['contexts'][0]['feed'], feed)
                self.assertEqual(result['contexts'][0]['feed_delay_seconds'], delay)
                self.assertNotIn('IEX_ONLY_NOT_CONSOLIDATED_MARKET', result['limitations'])
                self.assertIn('CONSOLIDATED_MARKET_FEED', result['limitations'])
                self.assertIn('CONSOLIDATED_VOLUME_AS_OF_RETAINED_BAR_NOT_GUARANTEED_FINAL', result['limitations'])

    def test_legacy_default_projection_is_exact_without_added_metadata(self):
        news, snaps = fixture()
        result = self.project(news, snaps)
        explicit = m.project(canonical_json_bytes(news), canonical_json_bytes(snaps), WATCH,
                             m.stamp(NOW), feed='iex')
        self.assertEqual(canonical_json_bytes(result), canonical_json_bytes(explicit))
        self.assertEqual(result['schema_version'], m.VERSION)
        self.assertNotIn('market_feed', result)
        self.assertNotIn('feed_delay_seconds', result['contexts'][0])
        self.assertIn('IEX_ONLY_NOT_CONSOLIDATED_MARKET', result['limitations'])

    def test_missing_consolidated_bars_do_not_invent_volume(self):
        news, snaps = fixture()
        snaps.pop('SPY')
        result = m.project(canonical_json_bytes(news), canonical_json_bytes(snaps), WATCH,
                           m.stamp(NOW), feed='delayed_sip')
        row = result['contexts'][0]
        self.assertEqual(row['status'], 'UNAVAILABLE')
        self.assertEqual(row['feed'], 'delayed_sip')
        self.assertEqual(row['feed_delay_seconds'], 900)
        self.assertNotIn('day_volume', row)

    def test_delayed_feed_freshness_has_explicit_delay_boundary(self):
        for age, expected in [(900, 'DELAYED'), (1800, 'DELAYED'), (1801, 'STALE')]:
            news, snaps = fixture()
            snaps['SPY']['minuteBar']['t'] = m.stamp(NOW - timedelta(seconds=age))
            result = m.project(canonical_json_bytes(news), canonical_json_bytes(snaps),
                               WATCH, m.stamp(NOW), feed='delayed_sip')
            with self.subTest(age=age):
                self.assertEqual(result['contexts'][0]['status'], expected)
                self.assertEqual(result['contexts'][0]['bar_age_seconds'], age)
                self.assertEqual(result['contexts'][0]['feed_delay_seconds'], 900)

    def test_sip_retains_normal_freshness_threshold(self):
        news, snaps = fixture()
        snaps['SPY']['minuteBar']['t'] = m.stamp(NOW - timedelta(seconds=901))
        result = m.project(canonical_json_bytes(news), canonical_json_bytes(snaps),
                           WATCH, m.stamp(NOW), feed='sip')
        self.assertEqual(result['contexts'][0]['status'], 'STALE')

    def test_unsupported_projection_feeds_are_rejected(self):
        news, snaps = fixture()
        for feed in ['all', 'otc', None, ['sip']]:
            with self.subTest(feed=feed), self.assertRaises(ValueError):
                m.project(canonical_json_bytes(news), canonical_json_bytes(snaps), WATCH,
                          m.stamp(NOW), feed=feed)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / 'store'
        self.store = m.CatalystStore(self.root)

    def test_roundtrip_idempotent_and_source_bytes_retained(self):
        projection, blobs = packet()
        self.assertTrue(self.store.append(projection, blobs)['written'])
        self.assertFalse(self.store.append(projection, blobs)['written'])
        self.assertEqual(self.store.verify()['capture_count'], 1)
        self.assertEqual(self.store.view(NOW)['articles'][0]['first_seen_at'], m.stamp(NOW))
        for value in blobs.values():
            self.assertEqual((self.root / 'evidence' / sha256_bytes(value)).read_bytes(), value)

    def test_revisions_append_preserve_first_seen_and_original(self):
        first, blobs = packet()
        self.store.append(first, blobs)
        original = (self.root / 'entries/00000001.json').read_bytes()
        next_at = NOW + timedelta(minutes=5)
        second, blobs2 = packet(at=next_at, headline='Updated agreement')
        self.store.append(second, blobs2)
        card = self.store.view(next_at)['articles'][0]
        self.assertEqual(card['first_seen_at'], m.stamp(NOW))
        self.assertEqual(card['revision_count'], 2)
        self.assertEqual(card['headline'], 'Updated agreement')
        self.assertEqual((self.root / 'entries/00000001.json').read_bytes(), original)

    def test_newly_updated_news_sorts_before_repeated_old_headlines(self):
        projection, blobs = packet()
        self.store.append(projection,blobs)
        second, raw = packet(at=NOW+timedelta(minutes=5),identity=456)
        news = json.loads(raw['news'])
        news['news'].append(json.loads(blobs['news'])['news'][0])
        raw['news'] = canonical_json_bytes(news)
        receipt = json.loads(raw['news_receipt'])
        receipt.update(body_sha256=sha256_bytes(raw['news']),size_bytes=len(raw['news']))
        raw['news_receipt'] = canonical_json_bytes(receipt)
        second = m.project(raw['news'],raw['snapshots'],WATCH,second['captured_at'])
        self.store.append(second,raw)
        self.assertEqual(self.store.view(NOW+timedelta(minutes=5))['articles'][0]['provider_id'],'456')

    def test_receipt_hash_watchlist_and_projection_must_match(self):
        for mutation in ('hash', 'watchlist', 'projection'):
            projection, blobs = packet()
            if mutation == 'hash': blobs['news'] += b' '
            if mutation == 'watchlist': projection['symbols'] = ['SPY']
            if mutation == 'projection': projection['contexts'][0]['price'] = '999'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): self.store.append(projection, blobs)

    def test_interrupted_publish_keeps_orphans_and_retry_recovers(self):
        projection, blobs = packet()
        publisher = m._publish_immutable
        def interrupted(staging, target, name, value):
            if name.endswith('.json'): raise OSError('fixture interruption')
            return publisher(staging, target, name, value)
        with patch.object(m, '_publish_immutable', side_effect=interrupted), self.assertRaises(OSError):
            self.store.append(projection, blobs)
        verified = self.store.verify()
        self.assertEqual(verified['capture_count'], 0)
        self.assertGreater(verified['orphan_evidence_count'], 0)
        self.store.append(projection, blobs)
        self.assertEqual(self.store.verify()['orphan_evidence_count'], 0)

    def test_kill_after_link_before_staging_cleanup_is_readable_and_retryable(self):
        projection, blobs = packet()
        self.store.append(projection, blobs)
        evidence = self.root/'evidence'/sha256_bytes(blobs['news'])
        staging = self.root/'staging'/('.publish-'+'a'*32+'.tmp')
        os.link(evidence,staging)
        self.assertEqual(self.store.verify()['staging_orphan_count'],1)
        self.assertEqual(self.store.view(NOW)['capture_count'],1)
        self.assertFalse(self.store.append(projection,blobs)['written'])
        self.assertTrue(staging.exists())  # No automatic evidence repair/deletion.

    def test_entry_sequence_gap_is_a_blocking_failure(self):
        self.store.append(*packet())
        (self.root/'entries/00000001.json').rename(self.root/'entries/00000002.json')
        with self.assertRaises(ValueError): self.store.verify()

    def test_retained_partial_transport_not_a_complete_capture(self):
        _, blobs = packet()
        self.store.retain_transport(blobs['news'], blobs['news_receipt'])
        self.assertEqual(self.store.verify()['orphan_evidence_count'], 2)
        self.assertIsNone(self.store.view(NOW))

    def test_tampering_and_sequence_gap_fail_closed(self):
        projection, blobs = packet()
        self.store.append(projection, blobs)
        path = self.root / 'evidence' / sha256_bytes(blobs['news'])
        path.chmod(0o600); path.write_bytes(b'{}')
        with self.assertRaises(ValueError): self.store.verify()
        with self.assertRaises(ValueError): self.store.view(NOW)

    def test_old_evidence_tampering_detected_even_when_latest_good(self):
        first, blobs = packet()
        self.store.append(first, blobs)
        second, blobs2 = packet(at=NOW+timedelta(minutes=5), identity=456)
        self.store.append(second, blobs2)
        path = self.root / 'evidence' / sha256_bytes(blobs['news'])
        path.chmod(0o600); path.write_bytes(b'{}')
        with self.assertRaises(ValueError): self.store.view(NOW+timedelta(minutes=5))

    def test_symlink_and_external_hardlink_rejected(self):
        projection, blobs = packet()
        self.store.append(projection, blobs)
        path = self.root / 'evidence' / sha256_bytes(blobs['news'])
        outside = self.root.parent / 'other'
        path.rename(outside); path.symlink_to(outside)
        with self.assertRaises((ValueError, RuntimeError)): self.store.verify()
        path.unlink(); os.link(outside, path)
        with self.assertRaises(ValueError): self.store.verify()

    def test_backward_clock_and_capacity_block_without_overwrite(self):
        projection, blobs = packet()
        self.store.append(projection, blobs)
        projection2, blobs2 = packet(at=NOW-timedelta(minutes=5))
        with self.assertRaises(ValueError): self.store.append(projection2, blobs2)
        with patch.object(m, 'MAX_CAPTURES', 1), self.assertRaises(ValueError):
            self.store.append(*packet(at=NOW+timedelta(minutes=5)))
        self.assertEqual(self.store.verify()['capture_count'], 1)

    def test_reading_does_not_create_or_repair_store(self):
        with self.assertRaises(RuntimeError): self.store.view(NOW)
        self.assertFalse(self.root.exists())

    def test_mixed_version_prefix_replays_without_rewriting_legacy_entry(self):
        self.store.append(*packet())
        original = (self.root / 'entries/00000001.json').read_bytes()
        self.store.append(*packet(at=NOW + timedelta(minutes=5), feed='sip'))
        self.store.append(*packet(at=NOW + timedelta(minutes=10), feed='delayed_sip'))
        records, receipt = self.store.verified_records()
        self.assertEqual(receipt['capture_count'], 3)
        self.assertEqual([r['schema_version'] for r in records],
                         [m.VERSION, m.CONSOLIDATED_VERSION, m.CONSOLIDATED_VERSION])
        self.assertEqual((self.root / 'entries/00000001.json').read_bytes(), original)
        self.assertEqual(self.store.view(NOW + timedelta(minutes=10))['market_feed'], 'delayed_sip')

    def test_bound_feed_prevents_relabeling_old_snapshots(self):
        legacy, old_blobs = packet()
        sip, new_blobs = packet(feed='sip')
        for projection, blobs in [(sip, old_blobs), (legacy, new_blobs)]:
            with self.assertRaises(ValueError):
                self.store.append(projection, blobs)
        self.assertFalse(self.root.exists())

    def test_consolidated_receipt_downgrade_or_feed_change_fails(self):
        for change in [('schema_version', 'blackpod.sentry_catalyst_get.v1'), ('feed', 'delayed_sip')]:
            result, blobs = packet(feed='sip')
            receipt = json.loads(blobs['snapshots_receipt'])
            if change[0] == 'feed':
                receipt['query']['feed'] = change[1]
            else:
                receipt[change[0]] = change[1]
            blobs['snapshots_receipt'] = canonical_json_bytes(receipt)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.store.append(result, blobs)

    def test_v2_record_cannot_claim_v1_projection_version(self):
        self.store.append(*packet(feed='sip'))
        path = self.root / 'entries/00000001.json'
        record = json.loads(path.read_bytes())
        record['schema_version'] = m.VERSION
        path.chmod(0o600)
        path.write_bytes(canonical_json_bytes(record))
        with self.assertRaises(ValueError):
            self.store.verify()


class ConsolidatedControlTests(unittest.TestCase):
    def config(self, base):
        result = {k: str(base / k) for k in ('station_root', 'runtime_root', 'experiment_root', 'historical_root', 'ui_root')}
        result.update(credentials_file=str(base / 'private/keys.yaml'), credential_format='GALACTICA_YAML')
        return result

    def test_explicit_controls_allow_only_consolidated_feeds(self):
        for feed in m.CONSOLIDATED_FEEDS:
            value = {'schema_version': m.CONSOLIDATED_VERSION, 'enabled': True,
                     'symbols': WATCH, 'feed': feed}
            self.assertEqual(m.control(value), value)
        for feed in ['iex', 'otc', None, ['sip']]:
            value = {'schema_version': m.CONSOLIDATED_VERSION, 'enabled': True,
                     'symbols': WATCH, 'feed': feed}
            with self.subTest(feed=feed), self.assertRaises(ValueError):
                m.control(value)

    def test_old_control_is_preserved_and_cannot_smuggle_feed(self):
        value = {'schema_version': m.VERSION, 'enabled': True, 'symbols': WATCH}
        self.assertEqual(m.control(value), value)
        for invalid in [{**value, 'feed': 'sip'},
                        {'schema_version': m.CONSOLIDATED_VERSION, 'enabled': True, 'symbols': WATCH}]:
            with self.assertRaises(ValueError):
                m.control(invalid)

    def test_collector_rejects_iex_before_keys_or_requests(self):
        with patch.object(service, 'paths') as paths, patch.object(service, 'parse_credentials') as keys:
            with self.assertRaises(ValueError):
                service.collect({}, WATCH, feed='iex', getter=lambda *a: self.fail('request'))
            paths.assert_not_called()
            keys.assert_not_called()

    def test_legacy_control_requires_explicit_feed_without_consuming_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.config(Path(directory).resolve())
            root, _ = service.paths(config)
            atomic_state(root / 'control.json', {'schema_version': m.VERSION,
                                                 'enabled': True, 'symbols': WATCH})
            before = (root / 'control.json').read_bytes()
            with patch.object(service, 'collect') as collect, patch.object(service, 'parse_credentials') as keys:
                self.assertEqual(service.cycle(config, now=NOW), 'MARKET_FEED_CONFIGURATION_REQUIRED')
            collect.assert_not_called()
            keys.assert_not_called()
            self.assertFalse((root / 'state.json').exists())
            self.assertEqual((root / 'control.json').read_bytes(), before)

    def test_cycle_uses_explicit_delayed_feed_without_reallocation_of_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.config(Path(directory).resolve())
            root, _ = service.paths(config)
            atomic_state(root / 'control.json', {'schema_version': m.CONSOLIDATED_VERSION,
                'enabled': True, 'symbols': WATCH, 'feed': 'delayed_sip'})
            getter = lambda *a: self.fail('provider not expected in fixture')
            receipt = {'status': 'CAPTURED', 'captured_at': m.stamp(NOW),
                       'market_feed': 'delayed_sip', 'feed_delay_seconds': 900}
            with patch.object(service, '_off'), patch.object(service, 'collect', return_value=receipt) as collect:
                self.assertEqual(service.cycle(config, now=NOW, getter=getter), 'CAPTURED')
            collect.assert_called_once_with(config, WATCH, feed='delayed_sip', getter=getter)
            state = json.loads((root / 'state.json').read_bytes())
            self.assertEqual(state['attempts_today'], 1)
            self.assertEqual(state['feed_delay_seconds'], 900)

    def test_configuration_cli_writes_only_explicit_consolidated_control(self):
        from contextlib import redirect_stdout
        import io
        from blackpod_build_week import shadow_station
        with tempfile.TemporaryDirectory() as directory:
            config = self.config(Path(directory).resolve())
            with patch.object(shadow_station, 'load_config', return_value=config), \
                 patch.object(service, '_off'), redirect_stdout(io.StringIO()):
                self.assertEqual(service.main(['configure', '--config', 'fixture.json',
                    '--symbols', ','.join(WATCH), '--enabled', '--feed', 'delayed_sip']), 0)
            value = json.loads((service.paths(config)[0] / 'control.json').read_bytes())
            self.assertEqual(value, {'schema_version': m.CONSOLIDATED_VERSION,
                'enabled': True, 'symbols': WATCH, 'feed': 'delayed_sip'})

    def test_default_capture_uses_sip_and_preserves_two_get_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            config = self.config(base)
            _, blobs = packet(feed='sip')
            calls = []
            def getter(kind, query, credentials):
                calls.append((kind, query))
                return blobs[kind], blobs[kind + '_receipt']
            with patch.object(service, '_off'), patch.object(service, 'utc_now', return_value=NOW), \
                 patch.object(service, '_read_regular', return_value=b'fixture'), \
                 patch.object(service, 'parse_credentials', return_value=PaperCredentials('fixture', 'fixture')):
                result = service.collect(config, WATCH, getter=getter)
            self.assertEqual([kind for kind, _ in calls], ['news', 'snapshots'])
            self.assertEqual(calls[-1][1]['feed'], 'sip')
            self.assertEqual(result['market_feed'], 'sip')
            self.assertEqual(result['feed_delay_seconds'], 0)
            self.assertEqual(m.CatalystStore(service.paths(config)[1]).view(NOW)['market_feed'], 'sip')

    def test_permission_failure_has_no_iex_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            config = self.config(base)
            _, blobs = packet(feed='sip')
            calls = []
            def getter(kind, query, credentials):
                calls.append((kind, query))
                if kind == 'snapshots':
                    raise capture.CatalystCaptureError('HTTP_ERROR', 403)
                return blobs[kind], blobs[kind + '_receipt']
            with patch.object(service, '_off'), patch.object(service, 'utc_now', return_value=NOW), \
                 patch.object(service, '_read_regular', return_value=b'fixture'), \
                 patch.object(service, 'parse_credentials', return_value=PaperCredentials('fixture', 'fixture')):
                with self.assertRaises(capture.CatalystCaptureError):
                    service.collect(config, WATCH, getter=getter)
            self.assertEqual([kind for kind, _ in calls], ['news', 'snapshots'])
            self.assertEqual(calls[-1][1]['feed'], 'sip')
            self.assertEqual(m.CatalystStore(service.paths(config)[1]).verify()['capture_count'], 0)


class ScheduleTests(unittest.TestCase):
    def test_hours_weekend_pause_and_dst(self):
        self.assertTrue(service.due(NOW, {}, True)[0])
        self.assertEqual(service.due(NOW, {}, False)[1], 'PAUSED')
        self.assertFalse(service.due(datetime(2026, 10, 17, 18, tzinfo=timezone.utc), {}, True)[0])
        self.assertFalse(service.due(datetime(2026, 10, 15, 4, tzinfo=timezone.utc), {}, True)[0])
        self.assertTrue(service.due(datetime(2026, 11, 2, 14, tzinfo=timezone.utc), {}, True)[0])

    def test_restart_budget_cooldown_and_clock_are_preserved(self):
        state = {'last_attempt_at': m.stamp(NOW), 'attempt_day': '2026-10-15', 'attempts_today': 1}
        self.assertFalse(service.due(NOW+timedelta(seconds=299), state, True)[0])
        self.assertTrue(service.due(NOW+timedelta(seconds=300), state, True)[0])
        state['attempts_today'] = 144
        self.assertEqual(service.due(NOW+timedelta(seconds=300), state, True)[1], 'DAILY_BUDGET_EXHAUSTED')
        state['attempts_today'] = True
        with self.assertRaises(ValueError): service.due(NOW+timedelta(seconds=300), state, True)
        self.assertEqual(service.due(NOW-timedelta(seconds=1), state, True)[1], 'CLOCK_BLOCKED')

    def test_naive_clock_rejected(self):
        with self.assertRaises(ValueError): service.due(NOW.replace(tzinfo=None),{},True)

    def test_no_catchup_burst_or_holiday_market_open_claim(self):
        self.assertTrue(service.due(datetime(2026, 11, 26, 18, tzinfo=timezone.utc), {}, True)[0])
        state = {'last_attempt_at': m.stamp(NOW-timedelta(days=1)), 'attempt_day': '2026-10-14', 'attempts_today': 144}
        self.assertTrue(service.due(NOW, state, True)[0])
