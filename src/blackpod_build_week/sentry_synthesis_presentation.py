"""Escaped, read-only presentation of retained Sentry interpretations and dissent.

Rendering performs no collection, inference, validation, or decision making. A
schema-valid response is still an unverified interpretation of limited inputs.
"""
from datetime import datetime
from html import escape
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


def _text(value):
    return escape(str(value) if value is not None else 'Unavailable', quote=True)


def _when(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return 'Unavailable'
        return parsed.astimezone(ZoneInfo('America/Los_Angeles')).strftime('%b %d · %I:%M:%S %p %Z')
    except (AttributeError, ValueError, TypeError, OverflowError):
        return 'Unavailable'


def _url(value):
    """Only explicit HTTPS evidence sources can become links."""
    if not isinstance(value, str) or any(ord(c) <= 32 or ord(c) == 127 for c in value):
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme == 'https' and parsed.hostname and parsed.username is None
                and parsed.password is None):
            return value
    except ValueError:
        pass
    return None


def _list(values, empty='None recorded.'):
    return ('<ul>' + ''.join('<li>' + _text(v) + '</li>' for v in values) + '</ul>') if values else '<p>' + _text(empty) + '</p>'


def _invalidation(value):
    # Version 1 nullable text is retained for replay; version 2 uses an explicit
    # tagged object compatible with the local constrained-decoding dialect.
    if isinstance(value, dict):
        return value.get('text') if value.get('status') == 'PROPOSED' else 'Not specified; not invented.'
    return value or 'Not specified; not invented.'


def render(value):
    """Return a document with the original draft and challenge kept separate."""
    status = value.get('status', 'UNAVAILABLE')
    labels = {'CHALLENGED_INTERPRETATION': 'Draft and challenge retained', 'DRAFT_ONLY': 'Draft only · challenge missing',
              'NOT_GENERATED': 'No synthesis generated', 'UNAVAILABLE': 'Synthesis unavailable',
              'FAILED': 'Synthesis attempt failed', 'UNCERTAIN': 'Synthesis state uncertain'}
    operational = value.get('operational') or {}
    report = value.get('report')
    auto = 'OFF' if value.get('auto_trading') == 'OFF' else 'UNVERIFIED'
    body = '<div class="badges"><b class="badge">' + _text(labels.get(status, 'Synthesis unavailable')) + '</b><span class="badge">Auto-trading ' + auto + '</span><span class="badge">NOT TRADE AUTHORITY</span></div>'
    body += '<p class="warning">Unverified headline-based interpretation. Structured validation checks format and evidence references; it does not establish truth, causation, consensus or a trading edge.</p>'
    if operational:
        body += '<p class="muted">Synthesis worker: ' + ('enabled' if operational.get('enabled') is True else 'paused or unavailable') + ' · Last attempt: ' + _text(operational.get('last_result', 'NOT_RUN')) + '</p>'
        if operational.get('last_attempt_at'):
            body += '<p class="muted">Last attempt time: ' + _text(_when(operational['last_attempt_at'])) + ' · Attempts today: ' + _text(operational.get('attempt_count_today')) + '</p>'
        if 'background_attempt_count_today' in operational:
            body += '<p class="muted">Background attempts today: ' + _text(operational['background_attempt_count_today']) + '/4 · Explicit manual diagnostics: ' + _text(operational.get('manual_attempt_count_today')) + ' · separate schedule allowance.</p>'
        if operational.get('last_result') == 'ATTEMPT_STARTED':
            body += '<p class="warning">An attempt is reserved and awaiting a retained completion. Any report below is from an earlier completed attempt. This status does not establish model progress.</p>'
        if operational.get('next_eligible_at'):
            body += '<p class="muted">Next eligible check: ' + _text(_when(operational['next_eligible_at'])) + ' · new headline evidence required.</p>'
    if not report:
        body += '<article class="card"><h2>No verified synthesis to display</h2><p>The source records remain available in Sentry. No sample interpretation or substitute report is shown. Check worker status, source verification and the auto-trading OFF gate.</p></article>'
    else:
        packet = report.get('context') or {}
        validation = report.get('validation')
        if validation:
            label = {'EXPLICIT_DEADLINE_VALIDATION':'Explicit deadline validation',
                'EXPLICIT_ERROR_CODE_DIAGNOSTIC':'Explicit error-code diagnostic',
                'EXPLICIT_RUNTIME_DIAGNOSTIC':'Explicit runtime diagnostic',
                'EXPLICIT_MODEL_SELECTION_VALIDATION':'Explicit model-selection validation'}.get(validation.get('purpose'),'Explicit v2 compatibility validation')
            body += '<article class="warning validation"><h2>' + label + '</h2><p>Retained inputs from ' + _text(_when(packet.get('as_of'))) + '. This separately recorded check uses the original saved headlines. It is not a fresh market assessment or a new forecast.</p><p>The failed parent attempt is preserved. Validation completion time is shown separately below.</p></article>'
        quality = packet.get('quality') or {}
        source = packet.get('source') or {}
        selected = packet.get('selection') or {}
        evidence = packet.get('evidence') or []
        retained_label = 'brief' if report.get('draft') else 'attempt'
        evidence_links = {}
        headline_number = 0
        for number, item in enumerate(evidence):
            kind = item.get('kind')
            if kind == 'HEADLINE':
                headline_number += 1
                label = 'Headline ' + str(headline_number)
            elif kind == 'PRICE_CONTEXT':
                named = ' / '.join(str(symbol) for symbol in item.get('symbols') or [])
                label = (named + ' price context') if named else 'Price context'
            elif kind == 'FEED_QUALITY':
                label = 'Feed quality'
            else:
                label = 'Evidence ' + str(number + 1)
            evidence_links[item.get('evidence_id')] = ('evidence-' + str(number), label)
        age = value.get('brief_age_seconds')
        if isinstance(age, int) and not isinstance(age, bool) and age >= 0:
            body += '<p class="muted">Retained ' + retained_label + ' age: ' + f'{age / 60:,.1f}' + ' minutes. The source snapshot time below remains the evidence cutoff.</p>'
            if age > 3600:
                body += ('<p class="warning">This retained brief is more than one hour old. It is historical interpretation, not a current market assessment. Newer observations may not be included.</p>' if report.get('draft') else
                         '<p class="warning">This retained attempt is more than one hour old and has no accepted draft. Check the worker status; no current interpretation is available.</p>')
        else:
            body += '<p class="muted">Retained ' + retained_label + ' age: unavailable. Check the original source snapshot and completion times below.</p>'

        def citations(identities):
            items = []
            for identity in identities or []:
                target = evidence_links.get(identity)
                if target:
                    anchor, label = target
                    items.append('<a href="#' + anchor + '">' + _text(label) + '</a>')
                else:
                    items.append(_text(identity) + ' (unavailable)')
            return '<p class="citations">Evidence: ' + (', '.join(items) or 'Unavailable') + '</p>'

        completion_label = 'Validation completed' if validation else 'Synthesis completed' if report.get('draft') else 'Attempt recorded'
        completion_note = 'Los Angeles time · original draft preserved' if report.get('draft') else 'No accepted draft; processing outcome retained'
        body += '<div class="grid"><article class="tile"><span>Source snapshot</span><strong>' + _text(_when(packet.get('as_of'))) + '</strong><small>Los Angeles time · retained inputs, not a live view</small></article><article class="tile"><span>' + completion_label + '</span><strong>' + _text(_when(report.get('completed_at'))) + '</strong><small>' + completion_note + '</small></article><article class="tile"><span>Headlines selected / omitted</span><strong>' + _text(selected.get('selected_headline_count')) + ' / ' + _text(selected.get('omitted_headline_count')) + '</strong><small>Omitted items were not supplied to the model</small></article></div>'
        body += '<p class="watchlist">Watchlist: ' + ' · '.join(_text(s) for s in packet.get('watchlist', [])) + '</p>'
        warnings = ['Headline-only evidence; article bodies and paywalled content were not read.',
                    'Independent sources are not verified. Repeated coverage is not independent confirmation.',
                    'Holdings and desk exposures are unavailable. This is a watchlist brief, not a portfolio assessment.',
                    'Price snapshots do not establish the response after a headline or performance relative to SPY/QQQ.']
        if quality.get('source_count') == 1:
            warnings.append('Single named news source in the supplied evidence; no independent-source corroboration.')
        if quality.get('news_truncated') is True:
            warnings.append('News pages are truncated. Coverage is incomplete and the missed-article count is unknown.')
        for key, label in [('stale_context_count', 'stale'), ('unavailable_context_count', 'unavailable'), ('future_context_count', 'future-dated')]:
            count = quality.get(key)
            if isinstance(count, int) and not isinstance(count, bool) and count > 0:
                warnings.append(str(count) + ' price context(s) are ' + label + '; check retained bar timestamps below.')
        if value.get('newer_evidence_available') is True:
            warnings.append('Newer Sentry evidence exists. This brief remains bound to its original snapshot.')
        coverage_label = 'coverage incomplete' if quality.get('news_truncated') is True else 'coverage unknown'
        body += '<details class="warning evidence-limits"><summary>Headlines only · ' + coverage_label + ' · no verified holdings</summary>' + _list(warnings) + '</details>'
        body += '<details class="card"><summary>Snapshot identity and retained limitations</summary><p>Context: ' + _text(packet.get('context_id')) + '</p><p>Source head: <code>' + _text(source.get('head_sha256')) + '</code> · Verified captures: ' + _text(source.get('capture_count')) + '</p>' + _list(packet.get('limitations') or [], 'No additional packet limitations recorded.') + '</details>'
        if validation:
            body += '<details class="card"><summary>Preserved parent attempt</summary><p>Parent report: <code>' + _text(validation.get('parent_report_id')) + '</code></p><p>Parent SHA-256: <code>' + _text(validation.get('parent_report_sha256')) + '</code></p><p>Purpose: ' + _text(validation.get('purpose')) + ' · Transport: ' + _text(validation.get('transport_schema_version')) + '</p></details>'
            if validation.get('scope'):
                body += '<p class="muted">Validation scope: ' + _text(validation['scope']) + ' · explicit manual check; normal monitoring hours and frequency are unchanged.</p>'
        draft = report.get('draft')
        challenge = report.get('challenge')
        body += '<h2>Oracle · original interpretation</h2><p class="muted">Model-generated reasoning from the retained packet. Each implication remains an unverified interpretation.</p>'
        if not draft:
            failure = ((report.get('provenance') or {}).get('oracle') or {}).get('failure_code')
            body += '<article class="card warning"><h3>Oracle draft unavailable</h3><p>No interpretation is substituted. A failed or missing response cannot authorize action.</p><p>Processing result: ' + _text(failure) + '</p></article>'
        else:
            overview = draft.get('overview') or {}
            body += '<article class="card"><h3>What picture is emerging?</h3><p>' + _text(overview.get('text')) + '</p>' + citations(overview.get('evidence_ids')) + '</article>'
            themes = draft.get('themes') or []
            if not themes:
                body += '<p>No themes were supported in the model draft. This does not establish an absence of market events.</p>'
            for theme in themes:
                body += '<article class="card"><span class="eyebrow">' + _text(theme.get('theme_id')) + ' · ORIGINAL DRAFT</span><h3>' + _text(theme.get('title')) + '</h3><p>' + _text(theme.get('interpretation')) + '</p>' + citations(theme.get('evidence_ids'))
                for implication in theme.get('implications') or []:
                    linkage = {'DIRECT_MENTION': 'Provider symbol tag · textual connection unverified', 'HYPOTHETICAL_READ_THROUGH': 'Hypothetical read-through · not established'}.get(implication.get('linkage'), 'Linkage unavailable')
                    body += '<div class="implication"><h4>' + _text(implication.get('symbol')) + ' <small>' + _text(linkage) + '</small></h4><div class="grid"><section><b>Trading lens</b><p>' + _text(implication.get('trading')) + '</p></section><section><b>Investment lens</b><p>' + _text(implication.get('investment')) + '</p></section></div></div>'
                body += '<div class="alternative"><b>Original alternative explanation</b><p>' + _text(theme.get('alternative')) + '</p></div><p><b>Proposed invalidation:</b> ' + _text(_invalidation(theme.get('proposed_invalidation'))) + '</p><p><b>Proposed review horizon:</b> ' + _text(theme.get('proposed_review_horizon', 'UNSPECIFIED')) + ' · not an approved investment horizon</p></article>'
            body += '<details class="card" open><summary>Unresolved questions</summary>' + _list(draft.get('unresolved_questions') or [], 'No questions recorded in the draft; this does not mean the evidence is complete.') + '</details>'
        body += '<h2>Separate challenge · dissent retained</h2><p class="muted">A separate review pass of the same evidence and original draft. This is not independent-source or independent-model consensus. EVIDENCE_BOUND means a reviewer assessment, not verified truth or approval.</p>'
        if not challenge:
            body += '<article class="card warning"><h3>Challenge unavailable · review incomplete</h3><p>The original draft remains visible as a draft. No approval, consensus or substitute challenge is inferred.</p></article>'
        else:
            for review in challenge.get('reviews') or []:
                body += '<article class="card dissent"><span class="eyebrow">' + _text(review.get('theme_id')) + ' · REVIEWER ASSESSMENT</span><h3>' + _text(review.get('status')) + '</h3><p>' + _text(review.get('reason')) + '</p>' + citations(review.get('evidence_ids')) + '<b>Reviewer alternative</b><p>' + _text(review.get('alternative')) + '</p><b>Missing evidence</b>' + _list(review.get('missing_evidence') or [], 'No additional evidence recorded by this reviewer; completeness is not established.') + '</article>'
            body += '<details class="card" open><summary>Reviewer limitations</summary>' + _list(challenge.get('overall_limitations') or []) + '<p>Reviewed original draft hash: <code>' + _text(challenge.get('draft_sha256')) + '</code></p></details>'
        body += '<details class="card"><summary>Model provenance · reported fields only</summary>'
        for role, title in [('oracle', 'Oracle'), ('challenge', 'Challenge')]:
            result = (report.get('provenance') or {}).get(role) or {}
            provenance = result.get('provenance') or {}
            fields = [('Status', result.get('status')), ('Processing result', result.get('failure_code'))]
            fields += [(key.replace('_', ' ').capitalize(), provenance[key]) for key in ('provider', 'model', 'model_revision', 'trace_id', 'requested_model', 'observed_model') if key in provenance]
            body += '<h3>' + title + '</h3><dl>' + ''.join('<dt>' + _text(key) + '</dt><dd>' + _text(v) + '</dd>' for key, v in fields if v is not None) + '</dl>'
            if not provenance:
                body += '<p>Model identity metadata unavailable; no model independence is claimed.</p>'
        body += '</details><details class="card source-folder"><summary>Source evidence · ' + str(len(evidence)) + ' retained item(s)</summary><p class="muted">Evidence supplied to the models. Full evidence IDs are retained below. Source links may require a subscription; an accessible headline does not establish access to the article body.</p>'
        for number, item in enumerate(evidence):
            data = item.get('data') or {}
            kind = item.get('kind')
            body += '<article class="card evidence" id="evidence-' + str(number) + '"><small>' + _text(item.get('evidence_id')) + ' · ' + _text(kind) + ' · ' + ' / '.join(_text(s) for s in item.get('symbols') or []) + '</small>'
            if kind == 'HEADLINE':
                target = _url(data.get('url'))
                title = _text(data.get('headline'))
                body += '<h3>' + ('<a href="' + _text(target) + '" target="_blank" rel="noopener noreferrer">' + title + '</a>' if target else title) + '</h3><p>Named source: ' + _text(data.get('source')) + '</p><p class="muted">Published ' + _text(_when(data.get('published_at'))) + ' · Updated ' + _text(_when(data.get('updated_at'))) + '<br>First seen ' + _text(_when(data.get('first_seen_at'))) + ' · Last seen ' + _text(_when(data.get('last_seen_at'))) + '</p>'
            elif kind == 'PRICE_CONTEXT':
                body += '<h3>Price context · ' + _text(data.get('status', 'UNAVAILABLE')) + '</h3><p>Change versus previous daily close: ' + _text(data.get('change_from_previous_close_pct')) + '% · Day volume: ' + _text(data.get('day_volume')) + '</p><p class="muted">Minute bar: ' + _text(_when(data.get('minute_at'))) + ' · Daily bar: ' + _text(_when(data.get('day_bar_at'))) + ' · Previous daily bar: ' + _text(_when(data.get('previous_day_bar_at'))) + '</p><p>Partial-market context. Day volume is not relative volume. This is not an event-time or benchmark comparison.</p>'
            elif kind == 'FEED_QUALITY':
                body += '<h3>Feed quality</h3><dl>' + ''.join('<dt>' + _text(key) + '</dt><dd>' + _text(v) + '</dd>' for key, v in data.items()) + '</dl>'
            body += '</article>'
        body += '</details>'
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="60"><title>BlackPod · Market brief</title><link rel="icon" href="data:,"><style>
body{margin:0;background:#0c1721;color:#e5edf4;font:15px/1.5 system-ui}main{max-width:1100px;margin:auto;padding:28px}h1{font-size:36px;letter-spacing:-.05em;margin:8px 0}h2{margin-top:30px;font-size:24px}h3{font-size:20px;margin:8px 0}h4{margin:8px 0}p{overflow-wrap:anywhere}a{color:#c2e4f2;text-decoration:none}a:hover{text-decoration:underline}small,.muted,.eyebrow,.tile span{color:#a8bdcb}.eyebrow{font-size:12px;letter-spacing:.06em}.badges{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0}.badge{padding:4px 10px;border:1px solid #456478;border-radius:20px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px}.tile,.card{background:#142633;border:1px solid #294554;border-radius:12px;padding:16px}.card{margin:14px 0}.tile strong,.tile small{display:block}.tile strong{margin:6px 0;font-size:18px}.warning{background:#493a1a;color:#ffe1a1;padding:16px;border-radius:10px;margin:14px 0}.warning li{margin:7px 0}.dissent{border-left:4px solid #c596d8}.implication{border-top:1px solid #345466;margin-top:16px;padding-top:8px}.implication h4 small{font-weight:400;display:block}.alternative{border-left:3px solid #6a94aa;padding-left:12px;margin-top:12px}.citations{font-size:12px;color:#a8bdcb}summary{cursor:pointer;font-weight:650}code{overflow-wrap:anywhere;font-size:12px}dt{font-weight:600;overflow-wrap:anywhere}dd{margin:0 0 8px;color:#a8bdcb;overflow-wrap:anywhere}footer{color:#a8bdcb;border-top:1px solid #304854;padding-top:18px;margin-top:30px}nav{display:flex;gap:18px;flex-wrap:wrap;margin:16px 0}.evidence{scroll-margin-top:20px}
</style><main><div class="eyebrow">BLACKPOD · ADVISORY OBSERVATION ONLY</div><h1>Sentry market brief</h1><p>What the saved headlines might mean. What remains uncertain.</p><nav><a href="/sentry">Sentry feed</a><a href="/sentry-audit">Feed quality audit</a><a href="/">Station status</a></nav>''' + body + '<footer>No trade recommendations, authorizations, orders, allocations or policy changes. The frozen reversal experiment is separate and unchanged. Refreshing this page reads saved records; it does not collect news or run models. All displayed source times use Los Angeles time.</footer></main></html>'
