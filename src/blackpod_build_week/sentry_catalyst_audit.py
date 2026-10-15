"""Read-only descriptive audit of verified catalyst observations. No provider calls.

Latency is observed discovery lag, not independently measured provider latency.
Nominal empty slots are not proven failures: attempt/control history is absent.
"""
from datetime import datetime, timedelta, time, timezone
from html import escape
from math import ceil
from pathlib import Path
import argparse
import json
import os
from zoneinfo import ZoneInfo

from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_catalyst import CatalystStore, clock, stamp

VERSION = 'blackpod.sentry_catalyst_audit.v1'
LA = ZoneInfo('America/Los_Angeles')
LIMITATIONS = [
    'DESCRIPTIVE_FEED_AUDIT_NOT_TRADING_EDGE_OR_EXECUTION_AUTHORITY',
    'FIRST_COMPLETE_CAPTURE_AND_WATCHLIST_CHANGE_ARE_BASELINES_NOT_LIVE_DETECTION',
    'OBSERVED_DISCOVERY_LAG_INCLUDES_POLLING_DOWNTIME_COVERAGE_AND_PROVIDER_DELAYS',
    'TOTAL_NEWS_UNIVERSE_AND_MISSED_ARTICLE_COUNT_UNKNOWN',
    'NO_HISTORICAL_ATTEMPT_CONTROL_OR_HEARTBEAT_LEDGER',
    'EMPTY_NOMINAL_SLOTS_ARE_NOT_PROVEN_FAILED_OR_REQUIRED_POLLS',
    'WEEKDAY_MONITORING_HOURS_ARE_NOT_AN_EXCHANGE_CALENDAR',
    'PRICE_FRESHNESS_IS_TIMESTAMP_AGE_NOT_QUOTE_QUALITY_OR_MARKET_COVERAGE',
    'LOCAL_RECEIPT_CLOCKS_NOT_INDEPENDENT_PUBLICATION_OR_ARRIVAL_ATTESTATIONS',
    'ORPHAN_TRANSPORT_NOT_PROMOTED_TO_COMPLETE_CAPTURES',
]


def milliseconds(delta):
    return (delta.days * 86400000000 + delta.seconds * 1000000 + delta.microseconds) // 1000


def distribution(values):
    ordered = sorted(v for v in values if v >= 0)
    def rank(n):
        return ordered[max(0, ceil(len(ordered) * n / 100) - 1)] if ordered else None
    return {'count': len(ordered), 'excluded_negative_count': sum(v < 0 for v in values),
            'min_ms': ordered[0] if ordered else None, 'p50_ms': rank(50), 'p95_ms': rank(95),
            'max_ms': ordered[-1] if ordered else None}


def _monitoring_slots(start, end):
    """Fully elapsed nominal five-minute slots, beginning with first capture slot.

    Read-only bounded analysis, not a change to the minimum-delay collector.
    DST changes fall outside these weekday LA monitoring windows.
    """
    first, last = start.astimezone(LA).date(), end.astimezone(LA).date()
    if (last - first).days > 3660:
        raise ValueError('audit window exceeds ten-year analysis bound')
    result = set()
    day = first
    while day <= last:
        if day.weekday() < 5:
            opening = datetime.combine(day, time(5), LA).astimezone(timezone.utc)
            for slot in range(144):
                at = opening + timedelta(minutes=5 * slot)
                if at + timedelta(minutes=5) <= end and int(at.timestamp()) // 300 >= int(start.timestamp()) // 300:
                    result.add(int(at.timestamp()) // 300)
        day += timedelta(days=1)
    return result


def build_report(records, verification, as_of):
    """Pure deterministic report for an explicit verified prefix and aware clock."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError('aware audit clock required')
    if verification['capture_count'] != len(records):
        raise ValueError('audit source count differs')
    projections = [r['projection'] for r in records]
    times = [clock(p['captured_at']) for p in projections]
    if times and (times[-1] > as_of or any(a > b for a, b in zip(times, times[1:]))):
        raise ValueError('audit clock precedes source or source clocks reversed')
    per_symbol, articles, versions = {}, {}, set()
    baseline_lag, discovery_lag, update_lag = [], [], []
    changes, truncated, returned_count = 0, 0, 0
    previous_watchlist = None
    for record, captured in zip(records, times):
        p = record['projection']
        selected = frozenset(p['symbols'])
        baseline = selected != previous_watchlist
        if previous_watchlist is not None and baseline:
            changes += 1
        previous_watchlist = selected
        truncated += int(p['news_truncated'])
        returned_count += len(p['articles'])
        for article in p['articles']:
            key = article['provider_id']
            version = (key, article['revision_sha256'])
            if key not in articles:
                articles[key] = {'baseline': baseline, 'symbols': set(article['symbols'])}
                lag = milliseconds(captured - clock(article['published_at']))
                (baseline_lag if baseline else discovery_lag).append(lag)
            else:
                articles[key]['symbols'].update(article['symbols'])
            if version not in versions:
                update_lag.append(milliseconds(captured - clock(article['updated_at'])))
                versions.add(version)
        for symbol in p['symbols']:
            row = per_symbol.setdefault(symbol, {'symbol': symbol, 'requested_capture_count': 0,
                'fresh_at_capture_count': 0, 'stale_at_capture_count': 0, 'unavailable_count': 0,
                'future_timestamp_count': 0, 'bar_ages': [], 'latest_bar_at': None, 'latest_capture_at': None})
            row['requested_capture_count'] += 1
            row['latest_capture_at'] = p['captured_at']
            context = next((c for c in p['contexts'] if c['symbol'] == symbol), None)
            row['latest_bar_at'] = context.get('minute_at') if context else None
            if not context or context['status'] == 'UNAVAILABLE':
                row['unavailable_count'] += 1
            else:
                age = milliseconds(captured - clock(context['minute_at']))
                row['bar_ages'].append(age)
                if age < 0:
                    row['future_timestamp_count'] += 1
                elif age <= 900000:
                    row['fresh_at_capture_count'] += 1
                else:
                    row['stale_at_capture_count'] += 1
    rows = []
    for symbol, data in sorted(per_symbol.items()):
        data = dict(data)
        data['bar_age_at_capture'] = distribution(data.pop('bar_ages'))
        latest = data['latest_bar_at']
        current_age = milliseconds(as_of - clock(latest)) if latest else None
        data['latest_bar_age_at_audit_ms'] = current_age
        data['latest_bar_status_at_audit'] = ('UNAVAILABLE' if current_age is None else
            'FUTURE_TIMESTAMP' if current_age < 0 else 'RECENT' if current_age <= 900000 else 'STALE')
        data['unique_headline_count'] = sum(symbol in a['symbols'] for a in articles.values())
        rows.append(data)
    total_pairs = sum(r['requested_capture_count'] for r in rows)
    complete_slots = {int(t.timestamp()) // 300 for t in times if t.astimezone(LA).weekday() < 5 and 5 <= t.astimezone(LA).hour < 17}
    expected_slots = _monitoring_slots(times[0], as_of) if times else set()
    captured_slots = expected_slots & complete_slots
    gaps = [milliseconds(b-a) for a, b in zip(times, times[1:])]
    latest_gap = milliseconds(as_of - times[-1]) if times else None
    result = {'schema_version': VERSION, 'authority': 'OBSERVATION_ONLY', 'as_of': stamp(as_of),
        'source': {'capture_count': len(records), 'head_sha256': verification['head_sha256'],
            'capture_ids': [r['capture_id'] for r in records], 'evidence_count': verification['evidence_count'],
            'orphan_evidence_count': verification['orphan_evidence_count'],
            'staging_orphan_count': verification['staging_orphan_count']},
        'window': {'first_capture_at': stamp(times[0]) if times else None, 'last_capture_at': stamp(times[-1]) if times else None,
                   'watchlist_change_count': changes, 'latest_complete_capture_age_ms': latest_gap},
        'news': {'unique_article_count': len(articles), 'observed_version_count': len(versions),
            'repeated_observation_count': returned_count - len(versions),
            'initial_or_watchlist_baseline_article_count': sum(a['baseline'] for a in articles.values()),
            'later_discovery_article_count': sum(not a['baseline'] for a in articles.values()),
            'baseline_publication_to_first_seen': distribution(baseline_lag),
            'later_publication_to_first_seen': distribution(discovery_lag),
            'version_update_to_first_seen': distribution(update_lag),
            'truncated_capture_count': truncated, 'capture_count': len(records),
            'overall_news_coverage_fraction': None, 'missed_article_count': None},
        'prices': {'symbol_capture_pairs': total_pairs,
            'fresh_at_capture_count': sum(r['fresh_at_capture_count'] for r in rows),
            'stale_at_capture_count': sum(r['stale_at_capture_count'] for r in rows),
            'unavailable_count': sum(r['unavailable_count'] for r in rows),
            'future_timestamp_count': sum(r['future_timestamp_count'] for r in rows), 'symbols': rows},
        'collection': {'nominal_completed_slots': len(expected_slots), 'slots_with_complete_capture': len(captured_slots),
            'slots_without_complete_capture': len(expected_slots - captured_slots),
            'inter_capture_wall_clock_gap': distribution(gaps),
            'inter_capture_gaps_over_ten_minutes': sum(g > 600000 for g in gaps),
            'http_request_latency': None, 'historical_failed_attempt_count': None,
            'nominal_slot_definition': 'WEEKDAY_LA_0500_1700_FIVE_MINUTE_FULLY_ELAPSED_SLOTS_FROM_FIRST_CAPTURE_SLOT'},
        'assessment': 'NO_VERIFIED_CAPTURES' if not records else 'DESCRIPTIVE_ONLY_NO_READINESS_OR_EDGE_APPROVAL',
        'limitations': LIMITATIONS}
    result['report_id'] = 'sentry-audit-' + sha256_bytes(canonical_json_bytes(result))
    return result


def audit(config, as_of=None):
    from .sentry_catalyst_service import paths
    from .shadow_station_collection import _off
    _off(Path(config['runtime_root']))
    _, root = paths(config)
    records, verification = CatalystStore(root).verified_records()
    result = build_report(records, verification, as_of or datetime.now(timezone.utc))
    _off(Path(config['runtime_root']))
    return result


def audit_status(config):
    from .sentry_catalyst_service import ERRORS
    try:
        return {'status': 'VERIFIED', 'report': audit(config)}
    except ERRORS:
        return {'status': 'UNAVAILABLE', 'report': None}


def render(value, *, live=True):
    def text(v):
        return escape(str(v), quote=True)
    def lag(v):
        return 'Unknown' if v is None else f'{v / 60000:,.1f} min'
    report = value.get('report')
    if not report:
        body = '<p class="warning">Audit unavailable. No substitute or cached result is shown. Check retained evidence and the OFF gate.</p>'
    else:
        n, p, c = report['news'], report['prices'], report['collection']
        facts = [
            ('Verified captures', report['source']['capture_count'], 'Complete observations only'),
            ('Later headline discoveries', n['later_discovery_article_count'], 'Startup/watchlist baselines excluded'),
            ('Typical discovery lag', lag(n['later_publication_to_first_seen']['p50_ms']), 'Publication → first complete observation'),
            ('Truncated news pages', f"{n['truncated_capture_count']} / {n['capture_count']}", 'Overall coverage remains unknown')]
        body = '<div class="grid">' + ''.join('<article><span>'+text(k)+'</span><strong>'+text(v)+'</strong><small>'+text(d)+'</small></article>' for k,v,d in facts) + '</div>'
        total = p['symbol_capture_pairs']
        body += '<h2>Price freshness when captured</h2><div class="bar">'
        for key, label, css in [('fresh_at_capture_count','Recent','recent'),('stale_at_capture_count','Stale','stale'),('unavailable_count','Unavailable','missing'),('future_timestamp_count','Future clock','missing')]:
            count = p[key]
            if count and total:
                body += '<span class="'+css+'" style="flex:'+str(count)+'" title="'+text(label)+' '+str(count)+'">'+str(count)+'</span>'
        body += '</div><p>' + text(p['fresh_at_capture_count'])+' recent · '+text(p['stale_at_capture_count'])+' stale · '+text(p['unavailable_count'])+' unavailable · '+text(p['future_timestamp_count'])+' future timestamps. Denominator: '+text(total)+' symbol/capture pairs. Recent means at most 15 minutes old, not a quality or trading approval.</p>'
        body += '<div class="table"><table><thead><tr><th>Symbol</th><th>Recent / requested</th><th>Typical bar age at capture</th><th>Latest bar age now</th><th>Headlines observed</th></tr></thead><tbody>'
        for r in p['symbols']:
            body += '<tr><td>'+text(r['symbol'])+'</td><td>'+text(r['fresh_at_capture_count'])+' / '+text(r['requested_capture_count'])+'</td><td>'+text(lag(r['bar_age_at_capture']['p50_ms']))+'</td><td>'+text(lag(r['latest_bar_age_at_audit_ms']))+' · '+text(r['latest_bar_status_at_audit'])+'</td><td>'+text(r['unique_headline_count'])+'</td></tr>'
        body += '</tbody></table></div><h2>What we can and cannot conclude</h2><p>'+text(c['slots_with_complete_capture'])+' of '+text(c['nominal_completed_slots'])+' fully elapsed nominal monitoring slots contain a complete capture. '+text(c['slots_without_complete_capture'])+' do not. Empty slots can reflect pauses, sleep, failures, or the collector’s minimum-delay timing; they are not proven failed requests.</p>'
        body += '<p>Overall headline coverage, missed-article count and HTTP request latency are <b>unknown</b>. The retained receipts do not contain request-start times, and complete captures are not an attempt history. Repeated observations and initial backfill are not new alerts.</p>'
        body += '<p>Discovery lag p95: <b>'+text(lag(n['later_publication_to_first_seen']['p95_ms']))+'</b> across '+text(n['later_publication_to_first_seen']['count'])+' non-negative later discoveries. Startup/watchlist baseline articles: '+text(n['initial_or_watchlist_baseline_article_count'])+'. This short sample cannot demonstrate predictive edge or justify trading.</p>'
        body += '<details><summary>Evidence and definitions</summary><p>First capture: '+text(report['window']['first_capture_at'])+'<br>Last capture: '+text(report['window']['last_capture_at'])+'<br>Audit clock: '+text(report['as_of'])+'<br>Source head: '+text(report['source']['head_sha256'])+'<br>Report: '+text(report['report_id'])+'</p><p>Percentiles use nearest rank. Discovery lags are measured only once per provider article; version lags once per observed revision. Negative clock lags are excluded and counted in the JSON. IEX is partial-market context. Watchlist changes create new baseline cohorts. No feed, polling, risk or trading policy is changed by this audit.</p></details>'
    refresh = '<meta http-equiv="refresh" content="60">' if live else ''
    json_url = '/sentry-audit.json' if live else 'report.json'
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' + refresh + '<link rel="icon" href="data:,"><title>Sentry · Feed quality</title><style>body{margin:0;background:#0c1721;color:#e5edf4;font:15px/1.6 system-ui}main{max-width:1100px;padding:28px;margin:auto}h1{font-size:34px;letter-spacing:-.04em}a{color:#b8dcec}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}article{padding:16px;background:#142633;border:1px solid #294554;border-radius:12px}article span,small{display:block;color:#b2c5d0}strong{display:block;font-size:28px}h2{margin-top:28px}.bar{display:flex;min-height:32px;border-radius:8px;overflow:hidden}.bar span{text-align:center;min-width:20px;box-sizing:border-box}.recent{background:#296c64}.stale{background:#806323}.missing{background:#754748}.table{overflow-x:auto}table{width:100%;border-collapse:collapse;text-align:left}th,td{padding:12px;border-bottom:1px solid #294554;white-space:nowrap}details{overflow-wrap:anywhere;background:#142633;padding:16px;border-radius:10px;margin-top:20px}.warning{background:#493a1a;padding:16px;border-radius:10px}</style><main><p>BLACKPOD · OBSERVATION ONLY</p><h1>Sentry feed quality</h1><p>Does the feed arrive soon enough, and what does it actually cover?</p>'+body+'<p><a href="http://127.0.0.1:5183/sentry">← Sentry headlines</a> · <a href="' + json_url + '">Audit JSON</a></p></main></html>'


def export_report(report, root, config):
    """Immutable idempotent report export, separate from all source/runtime roots."""
    from .decision_journal_store import _open_root, _open_child_directory, _publish_immutable, check_separate_root
    from .sentry_history_cache import read_regular
    root = Path(root).absolute()
    output = Path(config['repo_root']) / 'output'
    if '..' in root.parts or root == output or not root.is_relative_to(output):
        raise ValueError('report must use its own checkout output directory')
    for key in ('station_root','experiment_root','runtime_root','historical_root','ui_root'):
        check_separate_root(root, Path(config[key]))
    check_separate_root(root, Path(config['credentials_file']).parent)
    files = {'report.json': canonical_json_bytes(report), 'report.html': render({'status':'VERIFIED','report':report},live=False).encode()}
    manifest = {'schema_version': VERSION, 'report_id': report['report_id'],
                'files': {name: {'sha256':sha256_bytes(raw),'size_bytes':len(raw)} for name,raw in files.items()}}
    files['manifest.json'] = canonical_json_bytes(manifest)
    directory = _open_root(root, create=True)
    staging = _open_child_directory(directory, 'staging', create=True)
    try:
        if set(os.listdir(directory)) - {'report.json','report.html','manifest.json','staging'}:
            raise ValueError('unrelated report directory')
        # Conflict preflight before publishing anything else; never overwrite.
        for name, raw in files.items():
            if os.path.lexists(root/name) and read_regular(root/name) != raw:
                raise ValueError('immutable audit report conflict')
        for name, raw in files.items():
            if not os.path.lexists(root/name):
                _publish_immutable(staging,directory,name,raw)
    finally:
        os.close(staging); os.close(directory)
    return {'report_id':report['report_id'],'files':list(files)}


def verify_export(root, config):
    """Replay an immutable report against its original prefix after later appends."""
    from .contracts.mission_request import parse_strict_json_object_bytes
    from .sentry_history_cache import read_regular
    from .sentry_catalyst_service import paths
    from .shadow_station_collection import _off
    _off(Path(config['runtime_root']))
    root = Path(root).absolute()
    manifest = parse_strict_json_object_bytes(read_regular(root/'manifest.json',max_bytes=2*1024*1024))
    if (set(manifest) != {'schema_version','report_id','files'} or manifest['schema_version'] != VERSION
            or set(manifest['files']) != {'report.json','report.html'}):
        raise ValueError('invalid audit manifest')
    files = {}
    for name,ref in manifest['files'].items():
        raw = read_regular(root/name,max_bytes=2*1024*1024)
        if ref != {'sha256':sha256_bytes(raw),'size_bytes':len(raw)}:
            raise ValueError('audit export differs')
        files[name] = raw
    report = parse_strict_json_object_bytes(files['report.json'])
    _,store_root = paths(config)
    records,_ = CatalystStore(store_root).verified_records()
    count = report['source']['capture_count']
    if type(count) is not int or not 0 <= count <= len(records):
        raise ValueError('audit prefix unavailable')
    head = sha256_bytes(read_regular(store_root/'entries'/f'{count:08}.json')) if count else None
    if head != report['source']['head_sha256']:
        raise ValueError('audit source prefix differs')
    replay = build_report(records[:count],report['source'],clock(report['as_of']))
    if (replay != report or manifest['report_id'] != report['report_id']
            or render({'status':'VERIFIED','report':report},live=False).encode() != files['report.html']):
        raise ValueError('audit replay differs')
    _off(Path(config['runtime_root']))
    return {'verified':True,'report_id':report['report_id'],'source_capture_count':count,'provider_calls':0}


def main(argv=None):
    from .shadow_station import load_config
    from .sentry_catalyst_service import ERRORS
    parser = argparse.ArgumentParser(description='Offline Sentry latency/coverage audit; no collection or trading authority')
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--as-of', help='Explicit aware audit timestamp; must not precede the verified source prefix')
    parser.add_argument('--output-root', type=Path, help='Optional new immutable report directory under checkout/output')
    parser.add_argument('--verify-export',type=Path,help='Verify and replay a retained export against its original source prefix')
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.verify_export:
            if args.as_of or args.output_root:
                raise ValueError('verification cannot create or change a report')
            print(json.dumps(verify_export(args.verify_export,config),sort_keys=True))
            return 0
        selected_clock = clock(args.as_of) if args.as_of else None
        if selected_clock is not None and selected_clock > datetime.now(timezone.utc):
            raise ValueError('audit cannot use a future clock')
        report = audit(config, selected_clock)
        result = export_report(report,args.output_root,config) if args.output_root else report
        print(json.dumps(result,sort_keys=True))
        return 0
    except ERRORS:
        print(json.dumps({'status':'UNAVAILABLE','report':None,'provider_calls':0}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
