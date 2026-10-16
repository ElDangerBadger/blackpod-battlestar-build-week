"""Independent, bounded catalyst worker and offline administration CLI.

The host station owns lifecycle; this worker never calls the pilot collector.
"""
from datetime import datetime, timedelta, timezone
import argparse
import json
from pathlib import Path
import threading
from zoneinfo import ZoneInfo

from .decision_journal_store import JournalStoreError, check_separate_root
from .hashing import canonical_json_bytes
from .paper_account_probe import MAX_CREDENTIAL_BYTES, _read_regular, parse_credentials
from .sentry_catalyst import (CatalystStore, VERSION, CONSOLIDATED_VERSION,
    CONSOLIDATED_FEEDS, DEFAULT_SYMBOLS, clock, stamp, control, project, symbols)
from .sentry_catalyst_capture import market_get, CatalystCaptureError
from .shadow_station import atomic_state, read_state, service_lock
from .shadow_station_collection import _off

LA = ZoneInfo('America/Los_Angeles')
ERRORS = (ValueError, TypeError, KeyError, OSError, RuntimeError, JournalStoreError)


def utc_now():
    return datetime.now(timezone.utc)


def paths(config):
    root = Path(config['station_root']) / 'catalyst'
    for key in ('experiment_root', 'runtime_root', 'historical_root', 'ui_root'):
        check_separate_root(root, Path(config[key]))
    check_separate_root(root, Path(config['credentials_file']).parent)
    return root, root / 'evidence-store'


def due(now, state, enabled):
    """No catch-up requests: one attempt per five-minute slot, max 144/day.

    No exchange calendar is invented: these are weekday LA monitoring hours,
    including holidays, not a claim that an exchange is open.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('aware monitoring clock required')
    local = now.astimezone(LA)
    if not enabled:
        return False, 'PAUSED'
    if local.weekday() >= 5 or not 5 <= local.hour < 17:
        return False, 'OUTSIDE_MONITORING_HOURS'
    last = state.get('last_attempt_at')
    if last and clock(last) > now:
        return False, 'CLOCK_BLOCKED'
    if state.get('blocked_until') and now < clock(state['blocked_until']):
        return False, 'COOLDOWN'
    count = state.get('attempts_today', 0) if state.get('attempt_day') == local.date().isoformat() else 0
    if type(count) is not int or not 0 <= count <= 144:
        raise ValueError('invalid catalyst attempt state')
    if count >= 144:
        return False, 'DAILY_BUDGET_EXHAUSTED'
    if last and int(clock(last).timestamp()) // 300 == int(now.timestamp()) // 300:
        return False, 'WAITING_FOR_NEXT_SLOT'
    # Retained minimum delay also prevents two calls straddling a slot boundary.
    if last and (now - clock(last)).total_seconds() < 300:
        return False, 'WAITING_FOR_NEXT_SLOT'
    return True, 'DUE'


def collect(config, selected, *, feed='sip', getter=market_get):
    """At most two GETs, retaining any successful first request on second failure."""
    if feed not in CONSOLIDATED_FEEDS:
        raise ValueError('new catalyst captures require consolidated market data')
    selected = symbols(selected)
    root, store_root = paths(config)
    _off(Path(config['runtime_root']))
    store = CatalystStore(store_root)
    if store_root.exists():
        verified = store.verify()
        if verified['capture_count'] >= 4096 or verified['size_bytes'] > 256 * 1024 * 1024 - 4 * 1024 * 1024:
            raise ValueError('archive review required')
    credentials = parse_credentials(_read_regular(Path(config['credentials_file']), MAX_CREDENTIAL_BYTES), config['credential_format'])
    now = utc_now()
    named = ','.join(selected)
    query = {'symbols': named, 'start': stamp(now - timedelta(hours=24)), 'end': stamp(now),
             'limit': 50, 'sort': 'desc', 'include_content': 'false'}
    blobs = {}
    # Separate, bounded pending receipt preserves a successful response if the
    # other endpoint fails. These are not complete observations or alert cards.
    for kind, query in (('news', query), ('snapshots', {'symbols': named, 'feed': feed})):
        raw, receipt = getter(kind, query, credentials)
        blobs[kind], blobs[kind + '_receipt'] = raw, receipt
        store.retain_transport(raw, receipt)
    _off(Path(config['runtime_root']))
    captured_at = stamp(utc_now())
    projection = project(blobs['news'], blobs['snapshots'], selected, captured_at, feed=feed)
    result = store.append(projection, blobs)
    return {'status': 'CAPTURED', 'capture_id': result['capture_id'], 'captured_at': captured_at,
            'article_count': len(projection['articles']), 'news_truncated': projection['news_truncated'],
            'context_count': sum(row['status'] in ('OBSERVED', 'DELAYED') for row in projection['contexts']),
            'delayed_context_count': sum(row['status'] == 'DELAYED' for row in projection['contexts']),
            'market_feed': feed, 'feed_delay_seconds': projection['feed_delay_seconds']}


def cycle(config, *, now=None, getter=market_get):
    root, _ = paths(config)
    selected = control(read_state(root / 'control.json'))
    if selected['schema_version'] != CONSOLIDATED_VERSION:
        # Retain legacy evidence and controls, but require an explicit choice
        # before new transport. In particular, do not silently request IEX.
        return 'MARKET_FEED_CONFIGURATION_REQUIRED'
    state = read_state(root / 'state.json')
    if state and state.get('schema_version') != VERSION:
        raise ValueError('unsupported catalyst state')
    now = now or utc_now()
    admitted, reason = due(now, state, selected['enabled'])
    if not admitted:
        return reason
    _off(Path(config['runtime_root']))
    local = now.astimezone(LA)
    attempts = state.get('attempts_today', 0) if state.get('attempt_day') == local.date().isoformat() else 0
    state.update(schema_version=VERSION, last_attempt_at=stamp(now), attempt_day=local.date().isoformat(),
                 attempts_today=attempts + 1, status='ATTEMPT_STARTED', http_status=None, blocked_until=None)
    atomic_state(root / 'state.json', state)  # Consume budget before reading credentials or GETs.
    try:
        receipt = collect(config, selected['symbols'], feed=selected['feed'], getter=getter)
        state.update(receipt, last_success_at=receipt['captured_at'])
    except CatalystCaptureError as exc:
        state.update(status=exc.code, http_status=exc.http_status,
                     blocked_until=stamp(utc_now() + timedelta(hours=1 if exc.http_status in (401, 403, 429) else 0, minutes=15)))
    except ERRORS:
        state.update(status='VERIFICATION_OR_CAPTURE_BLOCKED', blocked_until=stamp(utc_now() + timedelta(minutes=15)))
    atomic_state(root / 'state.json', state)
    return state['status']


def worker(config, stop):
    root, _ = paths(config)
    # Independent lock and failure domain: catalyst outages never stop the pilot.
    try:
        with service_lock(root):
            while not stop.is_set():
                try:
                    atomic_state(root / 'health.json', {'schema_version': VERSION, 'heartbeat_at': stamp(utc_now())})
                    if (root / 'control.json').exists():
                        cycle(config)
                except ERRORS:
                    pass  # Fail closed; status independently exposes malformed evidence/control.
                stop.wait(30)
    except ERRORS:
        return


def start_worker(config, stop):
    thread = threading.Thread(target=worker, args=(config, stop), name='sentry-catalyst', daemon=True)
    thread.start()
    return thread


def status(config, now=None):
    root, store_root = paths(config)
    now = now or utc_now()
    result = {'schema_version': VERSION, 'authority': 'OBSERVATION_ONLY', 'status': 'NOT_CONFIGURED',
              'symbols': [], 'capture': None, 'collector': None, 'auto_trading': 'UNVERIFIED'}
    try:
        _off(Path(config['runtime_root']))
        result['auto_trading'] = 'OFF'
        selected = read_state(root / 'control.json')
        if not selected:
            return result
        selected = control(selected)
        state = read_state(root / 'state.json')
        health = read_state(root / 'health.json')
        heartbeat = health.get('heartbeat_at')
        alive = heartbeat is not None and 0 <= (now - clock(heartbeat)).total_seconds() < 120
        admitted, reason = due(now, state, selected['enabled'])
        selected_feed = selected.get('feed')
        if selected_feed is None:
            reason = 'MARKET_FEED_CONFIGURATION_REQUIRED'
        result.update(symbols=selected['symbols'], market_feed=selected_feed,
            feed_delay_seconds=(900 if selected_feed == 'delayed_sip' else 0) if selected_feed else None,
            status=reason if alive or selected_feed is None else 'WORKER_STALE_OR_STOPPED',
            collector={'enabled': selected['enabled'], 'reason': reason, 'worker_healthy': alive, 'last_attempt_at': state.get('last_attempt_at'),
                       'last_success_at': state.get('last_success_at'), 'last_result': state.get('status', 'NOT_RUN'),
                       'http_status': state.get('http_status'), 'blocked_until': state.get('blocked_until')})
        if store_root.exists():
            result['capture'] = CatalystStore(store_root).view(now)
            if result['capture'] and result['capture']['symbols'] != selected['symbols']:
                result['status'] = 'WATCHLIST_CHANGED_AWAITING_CAPTURE'
            elif (selected_feed is not None and result['capture']
                  and result['capture'].get('market_feed', 'iex') != selected_feed):
                result['status'] = 'MARKET_FEED_CHANGED_AWAITING_CAPTURE'
        return result
    except ERRORS:
        return {**result, 'status': 'UNAVAILABLE', 'capture': None}


def main(argv=None):
    from .shadow_station import load_config
    parser = argparse.ArgumentParser(description='Bounded observation-only Sentry; never submits orders')
    parser.add_argument('command', choices=['configure', 'status', 'verify', 'collect'])
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--symbols', help='Explicit comma-separated watchlist, maximum 10 symbols')
    parser.add_argument('--enabled', action='store_true')
    parser.add_argument('--feed', choices=CONSOLIDATED_FEEDS, default='sip',
                        help='Consolidated market feed; SIP needs entitlement, delayed SIP is 15 minutes delayed')
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        root, store_root = paths(config)
        if args.command == 'configure':
            if not args.symbols:
                raise ValueError('explicit watchlist required')
            selected = control({'schema_version': CONSOLIDATED_VERSION, 'enabled': args.enabled,
                                'symbols': args.symbols.split(','), 'feed': args.feed})
            _off(Path(config['runtime_root']))
            atomic_state(root / 'control.json', selected)
            result = selected
        elif args.command == 'collect':
            with service_lock(root):
                result = {'status': cycle(config)}  # Same hours, rate, budget and OFF gate as daemon.
        elif args.command == 'verify':
            result = CatalystStore(store_root).verify()
        else:
            result = status(config)
        print(json.dumps(result, sort_keys=True))
        return 0
    except ERRORS:
        print(json.dumps({'status': 'BLOCKED', 'authority': 'OBSERVATION_ONLY'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
