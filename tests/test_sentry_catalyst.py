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


def packet(at=NOW, **kwargs):
    news, snaps = fixture(at=at, **kwargs)
    raws = {'news': canonical_json_bytes(news), 'snapshots': canonical_json_bytes(snaps)}
    query = {'symbols': ','.join(WATCH), 'start': m.stamp(at-timedelta(hours=24)), 'end': m.stamp(at),
             'limit': 50, 'sort': 'desc', 'include_content': 'false'}
    for kind in ('news', 'snapshots'):
        receipt = {'schema_version': 'blackpod.sentry_catalyst_get.v1', 'method': 'GET', 'url': capture.URLS[kind],
                   'query': query if kind == 'news' else {'symbols': ','.join(WATCH), 'feed': 'iex'},
                   'captured_at': m.stamp(at), 'status': 200, 'body_sha256': sha256_bytes(raws[kind]), 'size_bytes': len(raws[kind])}
        raws[kind + '_receipt'] = canonical_json_bytes(receipt)
    return m.project(raws['news'], raws['snapshots'], WATCH, m.stamp(at)), raws


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
