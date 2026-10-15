"""Small server-rendered, read-only Sentry cards; escaped untrusted headlines."""
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo


def render(status):
    def text(value):
        return escape(str(value) if value is not None else '—', quote=True)
    def when(value):
        if not value:
            return 'Not yet recorded'
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(ZoneInfo('America/Los_Angeles')).strftime('%b %d · %I:%M:%S %p %Z')
        except (ValueError, TypeError, AttributeError):
            return 'Unavailable'
    def number(value, percent=False):
        try:
            return f'{float(value):+.2f}%' if percent else f'{float(value):,.0f}'
        except (ValueError, TypeError, OverflowError):
            return '—'
    labels = {'WAITING_FOR_NEXT_SLOT': 'Monitoring · five-minute polling', 'OUTSIDE_MONITORING_HOURS': 'Outside monitoring hours', 'COOLDOWN': 'Capture paused after a failure', 'WORKER_STALE_OR_STOPPED': 'Collector needs attention', 'PAUSED': 'Collection paused'}
    label = labels.get(status.get('status'), str(status.get('status', 'Unavailable')).replace('_', ' ').capitalize())
    capture = status.get('capture') or {}
    collector = status.get('collector') or {}
    contexts = {row['symbol']: row for row in capture.get('contexts', [])}
    tiles = []
    for symbol in status.get('symbols', []):
        row = contexts.get(symbol, {})
        fresh = row.get('status') in {'OBSERVED', 'STALE'}
        tiles.append('<article class="tile"><b>' + text(symbol) + '</b><strong>' +
            (text(number(row.get('change_from_previous_close_pct'), True)) if fresh else 'Unavailable') +
            '</strong><span>vs previous daily close</span><p>Day volume <b>' + text(number(row.get('day_volume'))) +
            '</b></p><small>' + text(row.get('status', 'UNAVAILABLE')) + ' · Bar: ' + text(when(row.get('minute_at'))) + '</small></article>')
    cards = []
    for item in capture.get('articles', []):
        chips = ''.join('<b class="chip">' + text(s) + '</b>' for s in item['symbols'])
        cards.append('<article class="card"><div>' + chips + '<span class="source">' + text(item['source']) +
            '</span></div><h2><a href="' + text(item['url']) + '" target="_blank" rel="noopener noreferrer">' +
            text(item['headline']) + '</a></h2><div class="times"><span>Published ' + text(when(item['published_at'])) +
            '</span><span>First seen ' + text(when(item['first_seen_at'])) + '</span><span>Updated ' +
            text(when(item['updated_at'])) + '</span></div><small>' + text(item['revision_count']) +
            ' observed version(s) · Last observed ' + text(when(item['last_seen_at'])) + ' · Provider article ' + text(item['provider_id']) + '</small></article>')
    warning = '<p class="warning">Latest news page is truncated. More headlines exist; coverage is incomplete.</p>' if capture.get('news_truncated') else ''
    stale_count = sum(row.get('status') == 'STALE' for row in capture.get('contexts', []))
    if stale_count:
        warning += '<p class="warning">' + str(stale_count) + ' price snapshot(s) are STALE. A recent capture does not mean recent prices. Check each bar timestamp.</p>'
    freshness = 'CAPTURE RECENT' if capture.get('status') == 'FRESH' else capture.get('status', 'NO_CAPTURE')
    failure = collector.get('last_result', 'NOT_RUN')
    if failure != 'CAPTURED':
        warning += '<p class="warning">Last collector result: ' + text(failure) + '. Previous cards, if present, are retained observations.</p>'
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="60"><title>BlackPod · Sentry</title><link rel="icon" href="data:,">
<style>body{margin:0;background:#0c1721;color:#e5edf4;font:15px/1.5 system-ui}main{max-width:1100px;margin:auto;padding:28px}h1{font-size:36px;letter-spacing:-.05em;margin:8px 0}h2{font-size:20px;line-height:1.4}a{color:#c2e4f2;text-decoration:none}a:hover{text-decoration:underline}.eyebrow,small,.times,.tile span{color:#9fb7c7}.badges{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0}.badge,.chip{padding:4px 10px;border:1px solid #345466;border-radius:20px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.tile,.card{background:#142633;border:1px solid #294554;border-radius:12px;padding:16px}.tile{padding:12px}.tile strong{display:block;font-size:22px;margin-top:2px}.tile small{font-size:10px}.tile span{font-size:12px}.tile p{margin:4px 0}.card{margin:14px 0}.chip{font-size:12px;margin-right:6px}.source{color:#a8c2d1}.times{display:flex;gap:18px;flex-wrap:wrap;font-size:13px;margin-bottom:10px}.warning{background:#493a1a;color:#ffe1a1;padding:14px;border-radius:10px}footer{color:#a8bdcb;border-top:1px solid #304854;padding-top:18px;margin-top:30px}nav{margin-top:24px}</style><main><div class="eyebrow">BLACKPOD · OBSERVATION ONLY</div><h1>Sentry catalyst feed</h1><p>What happened. When we saw it. How the watchlist moved.</p>''' + \
        '<div class="badges"><b class="badge">' + text(freshness) + '</b><span class="badge">Auto-trading ' + text(status.get('auto_trading')) + \
        '</span><span class="badge">IEX · partial-market context</span></div><p>Captured ' + text(when(capture.get('captured_at'))) + \
        ' · ' + text(label) + '</p>' + warning + '<div class="grid">' + ''.join(tiles) + \
        '</div><h2>Latest retained headlines</h2>' + (''.join(cards) or '<p>No verified headlines recorded yet. This does not mean there is no news.</p>') + \
        '<footer>Five-minute polling · weekdays 5 a.m.–5 p.m. Los Angeles · maximum 10 symbols.<br>Day volume is not relative volume. Price movement does not establish news causation. No sentiment scoring, trade recommendations or orders. Analyst, insider, legal-event and earnings verification are unavailable.<br>Cards refresh from saved evidence every minute; refreshing does not call providers. Source links open in your browser.</footer><nav><a href="http://127.0.0.1:5183/">Station status</a> · <a href="http://127.0.0.1:5181/?view=research">Frozen experiment</a></nav></main></html>'
