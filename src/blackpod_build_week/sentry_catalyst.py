"""Bounded evidence-only catalyst observations, separate from decisions and pilots."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
import fcntl
import os
from pathlib import Path
import re
import stat
from urllib.parse import urlsplit

from .contracts.mission_request import parse_rfc3339, parse_strict_json_object_bytes
from .decision_journal_store import (_open_root, _open_child_directory, _publish_immutable,
                                     _read_regular as _journal_read_regular)
from .hashing import canonical_json_bytes, sha256_bytes
from .trading_historical_intake import parse_historical_json

VERSION = 'blackpod.sentry_catalyst.v1'
CONSOLIDATED_VERSION = 'blackpod.sentry_catalyst.v2'
CONSOLIDATED_FEEDS = ('sip', 'delayed_sip')
MAX_CAPTURES = 4096
MAX_STORE_BYTES = 256 * 1024 * 1024
DEFAULT_SYMBOLS = ['SPY', 'QQQ', 'NVDA', 'AMZN', 'LULU', 'NKE', 'DG', 'PG', 'CLX', 'GOOGL']
LIMITATIONS = ['OBSERVATIONS_ONLY_NO_RECOMMENDATIONS_OR_ORDERS', 'IEX_ONLY_NOT_CONSOLIDATED_MARKET',
               'POLLING_NOT_REAL_TIME_OR_FIRST_TO_NEWS', 'NEWS_COVERAGE_AND_ENTITLEMENT_NOT_GUARANTEED',
               'PRICE_CONTEXT_IS_NOT_NEWS_CAUSATION', 'DAY_VOLUME_NOT_TIME_MATCHED_RELATIVE_VOLUME',
               'NO_ANALYST_INSIDER_LEGAL_OR_SENTIMENT_VERIFICATION']


def _read_regular(directory, name):
    raw, metadata = _journal_read_regular(directory, name)
    if len(raw) > 1024 * 1024:
        raise ValueError('unsafe or oversized retained evidence')
    return raw, metadata


def clock(value):
    return parse_rfc3339(value, 'catalyst timestamp')


def stamp(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def symbols(value):
    if (not isinstance(value, list) or not 1 <= len(value) <= 10 or len(set(value)) != len(value)
            or any(not isinstance(s, str) or not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,9}', s) for s in value)):
        raise ValueError('invalid bounded watchlist')
    return list(value)


def control(value):
    if not isinstance(value, dict) or type(value.get('enabled')) is not bool:
        raise ValueError('invalid catalyst control')
    if value.get('schema_version') == VERSION:
        if set(value) != {'schema_version', 'enabled', 'symbols'}:
            raise ValueError('invalid legacy catalyst control')
    elif value.get('schema_version') == CONSOLIDATED_VERSION:
        if (set(value) != {'schema_version', 'enabled', 'symbols', 'feed'}
                or value['feed'] not in CONSOLIDATED_FEEDS):
            raise ValueError('invalid consolidated catalyst control')
    else:
        raise ValueError('invalid catalyst control')
    return {**value, 'symbols': symbols(value['symbols'])}


def _text(value, maximum):
    if (not isinstance(value, str) or not value.strip() or len(value) > maximum
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError('invalid provider text')
    return value


def _number(value, positive=False, integer=False):
    if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
        raise ValueError('invalid market number')
    value = Decimal(value)
    if (not value.is_finite() or value < 0 or (positive and value == 0)
            or value > Decimal('1e16') or (integer and value != value.to_integral_value())):
        raise ValueError('invalid market number')
    return value


def _bar(value, now):
    if not isinstance(value, dict):
        raise ValueError('bar unavailable')
    t = clock(value['t'])
    if t > now + timedelta(seconds=5):
        raise ValueError('future bar')
    prices = {k: _number(value[k], positive=True) for k in ('o', 'h', 'l', 'c')}
    if prices['l'] > min(prices.values()) or prices['h'] < max(prices.values()):
        raise ValueError('inconsistent bar')
    return {**{k: str(v) for k, v in prices.items()}, 'v': str(_number(value['v'], integer=True)), 't': stamp(t)}


def project(news_raw, snapshots_raw, watchlist, captured_at, *, feed='iex'):
    """Pure projection; no event sentiment, profitability, or trading inference."""
    # The legacy default exists solely to reproduce retained v1 evidence. The
    # collector independently permits only consolidated feeds for new requests.
    if feed not in ('iex', *CONSOLIDATED_FEEDS):
        raise ValueError('unsupported catalyst market feed')
    consolidated = feed in CONSOLIDATED_FEEDS
    delay = 900 if feed == 'delayed_sip' else 0
    watchlist, now = symbols(watchlist), clock(captured_at)
    news, snapshots = parse_historical_json(news_raw), parse_historical_json(snapshots_raw)
    if (not isinstance(news, dict) or not isinstance(news.get('news'), list) or len(news['news']) > 50
            or not isinstance(snapshots, dict) or set(snapshots) - set(watchlist)):
        raise ValueError('unexpected provider response')
    token = news.get('next_page_token')
    if token is not None and (not isinstance(token, str) or len(token) > 2048):
        raise ValueError('invalid pagination')
    articles, seen = [], set()
    for item in news['news']:
        if not isinstance(item, dict):
            raise ValueError('invalid news item')
        identity = str(_number(item['id'], integer=True))
        if identity in seen:
            raise ValueError('duplicate provider article')
        seen.add(identity)
        published, updated = clock(item['created_at']), clock(item['updated_at'])
        if updated < published or updated > now + timedelta(seconds=5):
            raise ValueError('future or contradictory news time')
        named = item['symbols']
        if not isinstance(named, list) or len(named) > 1000 or any(not isinstance(s, str) for s in named):
            raise ValueError('invalid news symbols')
        matched = sorted(set(named) & set(watchlist))
        if not matched:
            continue
        url = _text(item['url'], 4096)
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('unsafe source link')
        article = {'provider_id': identity, 'headline': _text(item['headline'], 1000),
                   'source': _text(item['source'], 200), 'url': url, 'symbols': matched,
                   'published_at': stamp(published), 'updated_at': stamp(updated)}
        article['revision_sha256'] = sha256_bytes(canonical_json_bytes(article))
        articles.append(article)
    contexts = []
    for symbol in watchlist:
        row = {'symbol': symbol, 'status': 'UNAVAILABLE', 'reason': 'MISSING_OR_INVALID_BARS'}
        if consolidated:
            row.update(feed=feed, feed_delay_seconds=delay)
        try:
            snap = snapshots[symbol]
            day, previous, minute = (_bar(snap[k], now) for k in ('dailyBar', 'prevDailyBar', 'minuteBar'))
            if clock(previous['t']) >= clock(day['t']) or clock(day['t']) > clock(minute['t']):
                raise ValueError('bar ordering')
            with localcontext() as arithmetic:
                arithmetic.prec = 28
                arithmetic.rounding = ROUND_HALF_EVEN
                change = (Decimal(minute['c']) / Decimal(previous['c']) - 1) * 100
            age = int((now - clock(minute['t'])).total_seconds())
            context_status = ('DELAYED' if 0 <= age <= 1800 else 'STALE') if delay else ('OBSERVED' if age <= 900 else 'STALE')
            row = {'symbol': symbol, 'status': context_status, 'bar_age_seconds': age, 'minute_at': minute['t'],
                   'price': minute['c'], 'change_from_previous_close_pct': str(change),
                   'day_bar_at': day['t'], 'day_volume': day['v'],
                   'previous_day_bar_at': previous['t'], 'previous_day_volume': previous['v'],
                   'minute_volume': minute['v'], 'feed': feed}
            if consolidated:
                row['feed_delay_seconds'] = delay
        except (ValueError, TypeError, KeyError):
            pass
        contexts.append(row)
    result = {'schema_version': CONSOLIDATED_VERSION if consolidated else VERSION,
            'captured_at': stamp(now), 'symbols': watchlist,
            'articles': articles, 'contexts': contexts, 'news_truncated': bool(token),
            'limitations': LIMITATIONS, 'authority': 'OBSERVATION_ONLY'}
    if consolidated:
        result.update(market_feed=feed, feed_delay_seconds=delay,
            limitations=[('CONSOLIDATED_MARKET_FEED' if v == 'IEX_ONLY_NOT_CONSOLIDATED_MARKET' else v)
                         for v in LIMITATIONS] + ['CONSOLIDATED_VOLUME_AS_OF_RETAINED_BAR_NOT_GUARANTEED_FINAL',
                            'FIFTEEN_MINUTE_DELAYED_CONSOLIDATED_FEED' if delay else
                            'CONSOLIDATED_FEED_ENTITLEMENT_REQUIRED'])
    return result


class CatalystStore:
    """Immutable source blobs and hash-linked commit records using existing safe publishers.

    Incomplete writes may leave orphan blobs/staging, never a partial capture.
    There is no mutable head or evidence replacement. Capacity exhaustion blocks.
    """
    def __init__(self, root):
        self.root = Path(root).absolute()
        if '..' in self.root.parts:
            raise ValueError('unsafe catalyst root')

    @contextmanager
    def _directories(self, create=False):
        root = _open_root(self.root, create=create)
        descriptors = []
        try:
            for name in ('entries', 'evidence', 'staging'):
                descriptors.append(_open_child_directory(root, name, create=create))
            yield root, *descriptors
        finally:
            for fd in reversed(descriptors):
                os.close(fd)
            os.close(root)

    def _scan(self, entries, evidence, *, evidence_check=True):
        names, previous, records, used, identities = sorted(os.listdir(entries)), None, [], set(), set()
        if len(names) > MAX_CAPTURES:
            raise ValueError('capture capacity exceeded')
        for index, name in enumerate(names, 1):
            if name != f'{index:08}.json':
                raise ValueError('capture sequence differs')
            raw, _ = _read_regular(entries, name)
            record = parse_strict_json_object_bytes(raw)
            if (set(record) != {'schema_version', 'sequence', 'previous_sha256', 'capture_id', 'projection', 'evidence'}
                    or record['schema_version'] not in (VERSION, CONSOLIDATED_VERSION) or type(record['sequence']) is not int
                    or record['sequence'] != index or record['previous_sha256'] != previous):
                raise ValueError('capture chain differs')
            projection, refs = record['projection'], record['evidence']
            if (not isinstance(projection, dict)
                    or projection.get('schema_version') != record['schema_version']):
                raise ValueError('capture and projection versions differ')
            if not isinstance(refs, dict) or set(refs) != {'news', 'snapshots', 'news_receipt', 'snapshots_receipt'}:
                raise ValueError('capture evidence differs')
            expected_id = sha256_bytes(canonical_json_bytes({'projection': projection, 'evidence': refs}))
            if record['capture_id'] != expected_id or expected_id in identities:
                raise ValueError('capture identity differs')
            identities.add(expected_id)
            blobs = {}
            for kind, ref in refs.items():
                if (not isinstance(ref, dict) or set(ref) != {'sha256', 'size_bytes'}
                        or not re.fullmatch('[a-f0-9]{64}', ref['sha256'])
                        or type(ref['size_bytes']) is not int or not 0 < ref['size_bytes'] <= 1024 * 1024):
                    raise ValueError('invalid evidence reference')
                used.add(ref['sha256'])
                if evidence_check:
                    body, _ = _read_regular(evidence, ref['sha256'])
                    if len(body) != ref['size_bytes'] or sha256_bytes(body) != ref['sha256']:
                        raise ValueError('capture evidence hash differs')
                    blobs[kind] = body
            if evidence_check:
                self._validate(projection, blobs)
            elif projection.get('schema_version') not in (VERSION, CONSOLIDATED_VERSION) or projection.get('authority') != 'OBSERVATION_ONLY':
                raise ValueError('invalid capture projection')
            if records and clock(projection['captured_at']) < clock(records[-1]['projection']['captured_at']):
                raise ValueError('capture clock moved backwards')
            previous = sha256_bytes(raw)
            records.append(record)
        return records, previous, used

    @staticmethod
    def _validate(projection, blobs):
        from .sentry_catalyst_capture import validate_receipt
        if set(blobs) != {'news', 'snapshots', 'news_receipt', 'snapshots_receipt'} or any(not isinstance(v, bytes) or not 0 < len(v) <= 1024 * 1024 for v in blobs.values()):
            raise ValueError('invalid retained response set')
        snapshot_feed = None
        for kind in ('news', 'snapshots'):
            receipt = validate_receipt(parse_strict_json_object_bytes(blobs[kind + '_receipt']), kind)
            if (receipt['body_sha256'] != sha256_bytes(blobs[kind]) or receipt['size_bytes'] != len(blobs[kind])
                    or clock(receipt['captured_at']) > clock(projection['captured_at'])
                    or receipt['query']['symbols'] != ','.join(projection['symbols'])):
                raise ValueError('capture receipt binding differs')
            if kind == 'snapshots':
                snapshot_feed = receipt['query']['feed']
        # Infer replay provenance only from the validated, hash-bound receipt.
        # A v1 blob can never be relabeled as consolidated volume.
        if project(blobs['news'], blobs['snapshots'], projection['symbols'], projection['captured_at'],
                   feed=snapshot_feed) != projection:
            raise ValueError('capture replay differs')

    @staticmethod
    def _usage(*directories):
        # A kill between link publication and staging cleanup leaves legitimate
        # internal hardlinks. Accept only aliases wholly accounted for here;
        # any external hardlink remains a blocking integrity failure.
        total, inventory, observed = 0, {}, []
        for directory in directories:
            for name in os.listdir(directory):
                metadata = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if not stat.S_ISREG(metadata.st_mode):
                    raise ValueError('unsafe retained file')
                identity = (metadata.st_dev, metadata.st_ino)
                inventory[identity] = inventory.get(identity, 0) + 1
                observed.append((identity, metadata.st_nlink))
                total += metadata.st_size
        if any(count != inventory[identity] for identity, count in observed):
            raise ValueError('external evidence hardlink')
        return total

    def verified_records(self):
        """Return one fully verified immutable prefix and its source-head receipt."""
        with self._directories() as (_, entries, evidence, staging):
            total = self._usage(entries, evidence, staging)
            records, head, used = self._scan(entries, evidence)
            names = os.listdir(evidence)
            for name in names:
                if not re.fullmatch('[a-f0-9]{64}', name):
                    raise ValueError('unexpected evidence file')
                raw, _ = _read_regular(evidence, name)
                if sha256_bytes(raw) != name:
                    raise ValueError('orphan evidence hash differs')
            return records, {'capture_count': len(records), 'head_sha256': head, 'size_bytes': total,
                    'evidence_count': len(names), 'orphan_evidence_count': len(set(names) - used),
                    'staging_orphan_count': len(os.listdir(staging))}

    def verify(self):
        return self.verified_records()[1]

    def retain_transport(self, raw, receipt):
        """Keep successful GETs even when the paired endpoint or projection fails."""
        with self._directories(create=True) as (root, entries, evidence, staging):
            lock = os.open('.writer.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=root)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX)
                total = self._usage(entries, evidence, staging)
                if total + len(raw) + len(receipt) > MAX_STORE_BYTES:
                    raise ValueError('evidence capacity reached')
                for value in (raw, receipt):
                    digest = sha256_bytes(value)
                    if digest not in os.listdir(evidence):
                        _publish_immutable(staging, evidence, digest, value)
                    elif _read_regular(evidence, digest)[0] != value:
                        raise ValueError('immutable transport conflict')
            finally:
                os.close(lock)

    def append(self, projection, blobs):
        self._validate(projection, blobs)
        with self._directories(create=True) as (root, entries, evidence, staging):
            lock = os.open('.writer.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=root)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX)
                records, head, _ = self._scan(entries, evidence)
                refs = {k: {'sha256': sha256_bytes(v), 'size_bytes': len(v)} for k, v in blobs.items()}
                identity = sha256_bytes(canonical_json_bytes({'projection': projection, 'evidence': refs}))
                if any(r['capture_id'] == identity for r in records):
                    return {'written': False, 'capture_id': identity}
                if len(records) >= MAX_CAPTURES:
                    raise ValueError('capture capacity reached; archive review required')
                if records and clock(projection['captured_at']) < clock(records[-1]['projection']['captured_at']):
                    raise ValueError('capture clock moved backwards')
                total = self._usage(entries, evidence, staging)
                if total + sum(len(v) for v in blobs.values()) > MAX_STORE_BYTES:
                    raise ValueError('evidence capacity reached; archive review required')
                for value in blobs.values():
                    digest = sha256_bytes(value)
                    if digest not in os.listdir(evidence):
                        _publish_immutable(staging, evidence, digest, value)
                    else:
                        existing, _ = _read_regular(evidence, digest)
                        if existing != value:
                            raise ValueError('immutable evidence conflict')
                record = {'schema_version': projection['schema_version'], 'sequence': len(records) + 1, 'previous_sha256': head,
                          'capture_id': identity, 'projection': projection, 'evidence': refs}
                _publish_immutable(staging, entries, f'{len(records) + 1:08}.json', canonical_json_bytes(record))
                return {'written': True, 'capture_id': identity}
            finally:
                os.close(lock)

    def view(self, now):
        with self._directories() as (_, entries, evidence, staging):
            self._usage(entries, evidence, staging)
            records, _, _ = self._scan(entries, evidence, evidence_check=True)
            if not records:
                return None
            # Verify latest retained sources before showing current context.
            latest = records[-1]
            blobs = {k: _read_regular(evidence, ref['sha256'])[0] for k, ref in latest['evidence'].items()}
            for k, ref in latest['evidence'].items():
                if sha256_bytes(blobs[k]) != ref['sha256'] or len(blobs[k]) != ref['size_bytes']:
                    raise ValueError('latest evidence differs')
            self._validate(latest['projection'], blobs)
            first, revisions, cards = {}, {}, {}
            for record in records:
                for article in record['projection']['articles']:
                    key = article['provider_id']
                    first.setdefault(key, record['projection']['captured_at'])
                    revisions.setdefault(key, set()).add(article['revision_sha256'])
                    cards[key] = {**article, 'first_seen_at': first[key], 'last_seen_at': record['projection']['captured_at'],
                                  'revision_count': len(revisions[key])}
            projection = latest['projection']
            age = (now - clock(projection['captured_at'])).total_seconds()
            return {**projection, 'capture_count': len(records), 'status': 'FRESH' if 0 <= age <= 600 else 'STALE',
                    'age_seconds': max(0, int(age)), 'articles': sorted(cards.values(), key=lambda a: (clock(a['updated_at']), clock(a['last_seen_at']), a['provider_id']), reverse=True)[:50]}
