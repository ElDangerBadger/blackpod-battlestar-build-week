"""Standalone human review of a verified passive journal event; no action controls."""
from decimal import Context, Decimal, ROUND_DOWN, ROUND_HALF_EVEN, localcontext
from html import escape
from urllib.parse import urlsplit

from .contracts.desk_candidate_review import DeskReviewInput, validate_review_result
from .contracts.mission_request import parse_strict_json_object_bytes
from .hashing import sha256_bytes


def _text(value):
    return escape(str(value), quote=True)


def _number(value, digits=2, prefix=""):
    if value is None:
        return "—"
    with localcontext(Context(prec=256, rounding=ROUND_HALF_EVEN)):
        return prefix + format(Decimal(value), f",.{digits}f")


def _money(value):
    return _number(value, prefix="$")


def _fraction_percent(value):
    with localcontext(Context(prec=256)):
        return _number(Decimal(value) * 100) + "%"


def _packet(blobs, reference):
    raw = blobs.get(reference["sha256"])
    if raw is None or sha256_bytes(raw) != reference["sha256"] or len(raw) != reference["size_bytes"]:
        raise ValueError("presentation evidence is missing or differs from its binding")
    return parse_strict_json_object_bytes(raw)


def _label(value):
    return _text(value.replace("_", " ").lower().capitalize())


def _source_link(fact):
    url = fact["source_url"]
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("presentation source must be a public HTTPS URL")
    return '<a href="' + _text(url) + '" rel="noreferrer">' + _text(fact["issuer"]) + ' · ' + _text(fact["symbol"]) + '</a>'


def render_desk_review(event, blobs):
    """Render an event already verified with JournalStore. No sources are fetched."""
    if event.event_type != "SHADOW_DESK_REVIEW_RECORDED":
        raise ValueError("presentation requires a verified shadow desk review")
    review = DeskReviewInput.from_mapping(event.payload["review"])
    result = validate_review_result(event.payload["result"], review)
    market = _packet(blobs, review.sources["market_evidence"])
    analysis = _packet(blobs, review.sources["analysis_evidence"])
    issuer = _packet(blobs, review.sources["issuer_evidence"])
    budget = _packet(blobs, review.budget["proposal_evidence"])
    galactica = analysis.get("galactica")
    native = analysis.get("native", analysis)
    trading, investing = result["trading_plan"], result["investment_plan"]
    facts = {fact["symbol"]: fact for fact in issuer["facts"]}
    observations = {} if galactica is None else {row["symbol"]: row for row in galactica["spyglass"]["observations"]}
    with localcontext(Context(prec=256)):
        scenario_cap = (Decimal(result["budgets_usd"]["TRADING"]) * Decimal(review.policy["scenario_risk_fraction"])).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    pilot = "No entry proposed" if trading["symbol"] is None else _text(trading["symbol"]) + " · " + str(trading["qty"]) + " shares"
    pilot_description = ("No trading candidate passed all input, native-review, technical-challenge and whole-share sizing gates. Proposed entry quantity is zero."
        if trading["symbol"] is None else "A conditional execution and accounting test is proposed. It requires fresh evidence, installed limits and separate human authorization.")
    investment_cards = []
    for row in investing["candidates"]:
        source = facts.get(row["symbol"])
        mandate = "" if source is None else '<p>' + _text(source["mandate"]) + ' ' + _source_link(source) + '</p>'
        control = ('<p class="note">' + _text(row["symbol"]) + ' is the benchmark control. Comparing it with itself cannot demonstrate an investment edge.</p>'
            if row["symbol"] == review.policy["benchmark_symbol"] else "")
        investment_cards.append('<article class="research"><h3>' + _text(row["symbol"]) + ' <span class="pill">Research only</span></h3>'
            '<div class="size">' + str(row["qty"]) + ' shares <span>' + _money(row["estimated_notional_usd"]) + ' buffered scenario</span></div>'
            + mandate + '<p>' + _text(row["hypothesis"]) + '</p>' + control
            + '<details><summary>Conditions that invalidate the research proposal</summary><ul>'
            + ''.join('<li>' + _text(item) + '</li>' for item in row["invalidation_conditions"]) + '</ul></details></article>')
    if not investment_cards:
        investment_cards.append('<p>No investment research size passed the retained-input gates. Keep the proposed desk budget in reserve.</p>')
    candidate_rows = []
    category_names = {"TRADING_PILOT": "Conditional pilot", "INVESTMENT_RESEARCH": "Investment research", "DEFER": "Defer", "EXCLUDE": "Exclude"}
    for row in result["candidates"]:
        symbol, metrics = row["symbol"], row["metrics"]
        structure = observations.get(symbol)
        challenge = [] if structure is None else structure["challenge_assessment"]["current_reason_codes"]
        # The complete original reasons remain available, including the reason
        # for a technical gate and the original native disposition.
        reasons = '<br>'.join(_label(reason) for reason in row["reason_codes"])
        quote_note = ""
        if Decimal(metrics["ask"]) <= 0 or Decimal(metrics["bid"]) <= 0:
            quote_note = '<br><span class="bad">Missing positive two-sided quote</span>'
        elif metrics["spread_pct"] is not None and Decimal(metrics["spread_pct"]) > Decimal("0.50"):
            quote_note = '<br><span class="bad">Spread exceeds proposed 0.50% gate</span>'
        candidate_rows.append('<tr data-category="' + _text(row["category"]) + '"><td><b>' + _text(symbol) + '</b></td>'
            '<td><span class="pill ' + row["category"].lower() + '">' + category_names[row["category"]] + '</span></td>'
            '<td>' + _money(metrics["last"]) + '<small>' + _money(metrics["bid"]) + ' / ' + _money(metrics["ask"]) + quote_note + '</small></td>'
            '<td>' + _number(metrics["spread_pct"], 3) + '%</td><td>' + _number(metrics["return20_pct"])+ '% / ' + _number(metrics["return60_pct"]) + '%</td>'
            '<td>' + _text(row["native"]["candidate_state"]) + '<small>' + _text(row["native"]["senate_disposition"]) + '</small></td>'
            '<td>' + (', '.join(_label(item) for item in challenge) or ('No recent flag' if structure is not None else 'Not included'))
            + '<details><summary>Why this disposition</summary><p>' + reasons + '</p><p>Native confidence: '
            + _text(row["native"]["confidence_label"]) + '</p></details></td></tr>')
    issuer_rows = []
    for fact in issuer["facts"]:
        issuer_rows.append('<tr><td>' + _text(fact["symbol"]) + '</td><td>' + _text(fact["mandate"]) + '</td><td>'
            + ('Known action inside horizon; excluded' if fact["corporate_action_before_horizon"] else 'No action declared in retained fact')
            + '</td><td>' + _source_link(fact) + '<small>As of ' + _text(fact["as_of"]) + '</small></td></tr>')
    brigade = None if galactica is None else galactica["brigade"]
    brigade_status = "Not included" if brigade is None else ("Historical import only" if brigade["status"] == "HISTORICAL_INPUT_ONLY" else "Current inputs unavailable")
    brigade_detail = "Current forecasts and fresh opinions are unavailable; no inference ran."
    if brigade is not None and brigade["source_as_of"] is not None:
        brigade_detail += ' Retained source: ' + _text(brigade["source_as_of"]) + ' (' + _label(brigade["source_time_precision"]) + ').'
        brigade_detail += ' Missing members and partial rows remain recorded. Historical opinions cannot authorize a current trade.'
    source_rows = ''.join('<tr><td>' + _text(ref["path"]) + '</td><td class="hash">' + _text(ref["sha256"]) + '</td><td>'
        + str(ref["size_bytes"]) + '</td></tr>' for ref in event.evidence)
    native_report = native["outputs"]["oracle_report"]
    headline = native_report.get("headline", "Passive native market review")
    risk_regime = _text(result["native_summary"]["oracle_state"])
    scope_tag = "Synthetic fixture" if "synthetic" in review.account_id.lower() or "fixture" in review.account_id.lower() else "Retained account and market evidence"
    return '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BlackPod · Two-desk shadow review</title><style>
:root{--bg:#edf1f5;--ink:#182536;--muted:#536578;--blue:#18567d;--line:#d4dee7;--red:#963a38;--amber:#795014}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 system-ui,-apple-system,sans-serif}
main{max-width:1320px;margin:auto;padding:32px}header{background:#142c41;color:#fff;border-radius:16px;padding:30px 34px;margin-bottom:24px}
.eyebrow{font-size:12px;text-transform:uppercase;letter-spacing:.14em;color:#9fcae6}h1{font-size:34px;line-height:1.2;margin:8px 0 16px}h2{font-size:22px;margin:0 0 18px}h3{margin:0 0 12px;font-size:19px}
header p{max-width:950px;margin:12px 0;color:#d1e1ed}.badges{display:flex;gap:10px;flex-wrap:wrap}.badge{padding:5px 12px;border:1px solid #81a6c0;border-radius:6px;font-size:12px;font-weight:700}.off{color:#dcf5ec;border-color:#65ac96}
.meta{font-size:12px;color:#b3c5d3}.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}section,.card{background:#fff;border:1px solid var(--line);padding:24px;border-radius:12px;margin-bottom:20px}.grid .card{margin-bottom:0}
.stat{font-size:31px;font-weight:720;letter-spacing:-.02em}.stat small{font-size:13px;color:var(--muted);font-weight:500;margin-left:8px}.muted,small{color:var(--muted)}small{display:block;font-size:12px}p{margin:10px 0 15px}.pill{display:inline-block;font-size:11px;font-weight:700;background:#edf2f6;border-radius:5px;padding:3px 7px;line-height:1.4;white-space:nowrap}
.defer,.exclude{color:var(--red);background:#f8e9e8}.investment_research{background:#e8f1f7;color:var(--blue)}.trading_pilot{background:#e7f4ee;color:#196348}.note{border-left:3px solid #caa76b;padding:10px 14px;background:#faf5ea}.bad{color:var(--red)}a{color:var(--blue);text-decoration-thickness:1px;text-underline-offset:3px}
.research{border-top:1px solid var(--line);padding-top:18px;margin-top:16px}.size{font-size:23px;font-weight:700}.size span{font-size:14px;font-weight:500;color:var(--muted);margin-left:12px}.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}th{text-align:left;background:#f2f5f8;color:#42596e;font-size:11px;text-transform:uppercase;letter-spacing:.03em}td,th{padding:12px 10px;vertical-align:top;border-bottom:1px solid var(--line)}td.hash{font-family:ui-monospace,monospace;font-size:10px;word-break:break-all}details{margin:8px 0}summary{cursor:pointer;color:var(--blue)}details p{font-size:12px}ul,ol{padding-left:22px}li{margin:6px 0}
.toolbar{display:flex;gap:12px;align-items:center;margin-bottom:18px;flex-wrap:wrap}.toolbar label{font-size:12px;color:var(--muted)}select,input{font:inherit;border:1px solid var(--line);border-radius:6px;padding:6px 10px;background:white}.legend{font-size:12px;color:var(--muted)}.flow{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:18px 0}.flow span{padding:7px 10px;background:#eef3f7;border-radius:6px;font-size:12px}.flow b{color:#6488a3}footer{font-size:12px;color:var(--muted);padding:8px 2px 28px;overflow-wrap:anywhere}
@media(max-width:850px){main{padding:15px}.grid{grid-template-columns:1fr}header{padding:24px}h1{font-size:27px}section,.card{padding:18px}.size span{display:block;margin-left:0}}@media print{body{background:white}main{padding:0}.toolbar{display:none}section,header,.card{break-inside:avoid;box-shadow:none}header{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
</style></head><body><main><header><div class="eyebrow">BlackPod · Two independently governed desks</div>
<h1>Two-desk shadow candidate review</h1><div class="badges"><span class="badge off">AUTO-TRADING AUTHORITY OFF</span><span class="badge">PAPER · SHADOW ONLY</span><span class="badge">NO ORDER AUTHORIZATION</span></div>
<p>''' + pilot_description + ''' Investment sizes are proposed research scenarios. Desk ownership and capital limits remain inactive.</p>
<div class="meta">''' + scope_tag + ' · market capture ' + _text(result["market_as_of"]) + ' · review ' + _text(review.recorded_at) + '''<br>Recorded review authority only; current runtime status is checked separately.</div></header>
<div class="grid"><article class="card"><div class="eyebrow" style="color:var(--blue)">TRADING desk</div><h2>''' + pilot + '''</h2>
<div class="stat">''' + _money(result["budgets_usd"]["TRADING"]) + '''<small>fixed inactive budget</small></div>
<p>''' + _label(trading["status"]) + ' · proposed entry cap ' + _money(trading["max_entry_notional_usd"]) + '''.</p>
<p class="note">Oracle ''' + risk_regime + ' · Senate favorable ' + str(result["native_summary"]["senate_counts"]["FAVORABLE"]) + '''. Expected return is unknown. A functional accounting test cannot establish a trading edge.</p>
</article><article class="card"><div class="eyebrow" style="color:var(--blue)">INVESTMENT desk</div><h2>Research before allocation</h2>
<div class="stat">''' + _money(result["budgets_usd"]["INVESTMENT"]) + '''<small>fixed inactive budget</small></div>
<p>''' + str(investing["horizon_days"]) + '-day proposed research horizon · ' + _money(investing["total_notional_usd"]) + ' combined scenario · ' + _money(investing["cash_reserve_usd"]) + ''' retained reserve.</p>
<p class="note">Issuer mandates describe exposure. Independent economic and fundamental evidence is still needed for an allocation decision.</p></article></div>
<section style="margin-top:20px"><h2>Capital stays inside the recorded testing envelope</h2><p>The captured account equity was ''' + _money(budget["basis"]["equity_usd"]) + ' at ' + _text(budget["basis"]["captured_at"]) + '. The user’s 25% testing envelope is ' + _money(budget["test_cap_usd"]) + '; each desk receives half, leaving ' + _money(budget["unassigned_test_reserve_usd"]) + ' in test rounding reserve and ' + _money(budget["outside_test_usd"]) + ''' outside the test. These are fixed amounts from that capture, with no perpetual 50/50 rebalancing.</p>
<p>Every authority is disabled. No budget activation, capital transfer, installed ownership, executable order or realized trade P&amp;L exists for this review.</p></section>
<section><h2>Investment research scenarios</h2>''' + ''.join(investment_cards) + '''
<p class="legend">A ''' + _fraction_percent(review.policy["price_buffer_fraction"]) + ' price buffer and a proposed ' + _fraction_percent(review.policy["investment_candidate_fraction"]) + '''-of-desk cap per candidate produce whole-share scenarios. Exact decimal costs are retained in the journal; displayed amounts are rounded for reading. Distributions and splits require source-aware accounting before any total-return evaluation.</p></section>
<section><h2>Candidate board · ''' + str(len(result["candidates"])) + ''' symbols</h2><p>Native attention, technical observations and issuer research have distinct meanings. Price-derived Oracle, candidate and Senate evidence shares one market source; their labels are not independent forecasts.</p>
<div class="toolbar"><label for="desk-filter">Disposition</label><select id="desk-filter"><option value="">All candidates</option><option value="TRADING_PILOT">Conditional pilots</option><option value="INVESTMENT_RESEARCH">Investment research</option><option value="DEFER">Deferred</option><option value="EXCLUDE">Excluded</option></select><label for="symbol-filter">Symbol</label><input id="symbol-filter" placeholder="Search symbol" maxlength="16"><span id="visible-count" class="legend"></span></div>
<div class="table-wrap"><table id="candidates"><thead><tr><th>Symbol</th><th>Disposition</th><th>Last / bid / ask</th><th>Spread</th><th>20d / 60d price return</th><th>Native attention / Senate</th><th>Spyglass &amp; reasons</th></tr></thead><tbody>''' + ''.join(candidate_rows) + '''</tbody></table></div>
<p class="legend">IEX is a single-exchange feed, not consolidated liquidity. Returns are observed price changes, not forecasts. Mean 14-bar true range supplies the sizing scenario; it differs from Navigator’s Wilder ATR. Unproven same-day daily bars are excluded from history calculations. Spyglass’s proposed challenge window is 30 calendar days at the original market capture; all older detections remain retained.</p></section>
<section><h2>What is connected in this review</h2><div class="flow"><span>Frozen market observations</span><b>→</b><span>Oracle → native candidates → Senate</span><b>+</b><span>Spyglass structure</span><b>+</b><span>Issuer evidence</span><b>→</b><span>Shadow review → passive journal</span></div>
<div class="table-wrap"><table><thead><tr><th>Component</th><th>Actual use</th><th>Decision authority</th></tr></thead><tbody>
<tr><td>Oracle / native candidates / Senate</td><td>Reviewed pure native calculations on the frozen packet. ''' + _text(headline) + '''</td><td>Observations and passive review only; no approval.</td></tr>
<tr><td>Spyglass</td><td>''' + ('Not included in this event' if galactica is None else 'Existing Galactica analyze_structure on retained daily OHLCV. Recent bearish patterns, downward breaks and inadequate resistance headroom defer a trading pilot.') + '''</td><td>Technical challenge only.</td></tr>
<tr><td>Brigade</td><td>''' + brigade_status + '. ' + brigade_detail + '''</td><td>No current vote or authorization.</td></tr>
<tr><td>Council / Governor / Secretary outcomes</td><td>Existing BuildWeek stage adapters remain connected in the mission workflow. This separate review reuses candidate and Senate logic; it does not rerun stage authorization.</td><td>Existing mission semantics preserved.</td></tr>
<tr><td>Operator / Navigator / execution controls</td><td>Existing action and Navigator SHADOW workflow remains unchanged. This review has no execution hook.</td><td>SHADOW handoff is not trading approval; automation stays OFF.</td></tr>
<tr><td>ModelDock / Sentry views / Admiral</td><td>Optional ModelDock commentary and read-only Sentry research views retain their existing interfaces. Admiral is the fleet display. None was invoked as a new forecast source here.</td><td>No additional decision authority.</td></tr>
</tbody></table></div></section>
<section><h2>Bounded paper test proposal · prerequisites still open</h2><div class="grid"><div><h3>Proposed limits</h3><ul>
<li>One active entry and one completed entry/exit cycle.</li><li>Entry cap ''' + _money(trading["max_entry_notional_usd"]) + '; scenario loss cap ' + _money(scenario_cap) + ' from ' + _fraction_percent(review.policy["scenario_risk_fraction"]) + ''' of the trading budget.</li>
<li>Whole-share quantity is the smaller of cash-cap and scenario-risk sizes; ''' + _fraction_percent(review.policy["price_buffer_fraction"]) + ' price buffer and ' + _number(review.policy["atr_multiple"]) + ''' ATR distance.</li><li>Thirty-minute time exit in a regular session; no overnight position in the functional test.</li>
<li>Proposal expires ''' + _text(trading["expiry"]) + '. Current proposed quantity: ' + str(trading["qty"]) + '. Estimated entry notional: ' + _money(trading["estimated_notional_usd"]) + '''.</li></ul><p class="note">Stop distance is a scenario calculation. Gaps, slippage, fees and failed exits can exceed it; it is not a guaranteed maximum loss.</p></div>
<div><h3>Before any separately authorized order</h3><ol><li>Refresh source-bound quotes, completed bars, account, positions, open orders, corporate actions and market clock in a regular session.</li>
<li>Resolve native dissent and technical challenges. Supply current Brigade forecasts with explicit provenance before treating Brigade as current evidence.</li>
<li>Authorize and install account-specific desk ownership and bounded limits; verify consolidated exposure and exclusive position ownership.</li>
<li>Approve the exact symbol, quantity, maximum price, exit procedure, expiry and abort/recovery conditions. Auto-trading remains OFF.</li>
<li>Exercise fee, timestamp, partial-fill, cancellation and interrupted-entry/exit capture before relying on net accounting.</li></ol></div></div></section>
<section><h2>Research context and evaluation</h2><div class="table-wrap"><table><thead><tr><th>Symbol</th><th>Retained issuer mandate</th><th>Horizon issue</th><th>Primary source</th></tr></thead><tbody>''' + ''.join(issuer_rows) + '''</tbody></table></div>
<p>Known corporate actions inside the proposed horizon are excluded pending supported accounting. A missing positive ask or another input failure must be resolved before sizing a research candidate. ETNs and other structures outside the initial equity accounting scope are excluded.</p>
<p>For a future investment thesis, predeclare the economic rationale, alternative explanation, total-return benchmark, drawdown/concentration limits, invalidation conditions and evaluation date. SPY and lower-volatility or quality funds can still share substantial US-equity and technology exposure; distinct desk ownership does not remove correlation.</p>
<p>Evaluate a functional paper cycle by captured fills, fees, entry/exit completion, slippage and recovered ownership. Evaluate a later investment thesis by its declared horizon and falsification conditions. Append linked observations and evaluations without rewriting this review. A shadow or non-executed scenario has no realized trade P&amp;L.</p></section>
<section><details><summary>Retained evidence and reproducibility</summary><p>Event ''' + _text(event.event_id) + ' · review ' + _text(review.review_id) + '''. A verified journal retains the input, raw observations, issuer text, historical opinions, code fingerprints and original output. It can replay without the sibling checkouts. It establishes byte and calculation consistency, not provider attestation or predictive performance.</p><div class="table-wrap"><table><thead><tr><th>Evidence path</th><th>SHA-256</th><th>Bytes</th></tr></thead><tbody>''' + source_rows + '''</tbody></table></div></details></section>
<footer>BlackPod shadow review · recorded ''' + _text(review.recorded_at) + ''' · All sizes, hypotheses, horizons and challenge parameters introduced here are proposals. No order was submitted, no money moved, and no automated trading authority was enabled.</footer></main>
<script>(()=>{const rows=[...document.querySelectorAll('#candidates tbody tr')],desk=document.getElementById('desk-filter'),symbol=document.getElementById('symbol-filter'),count=document.getElementById('visible-count');function filter(){let n=0;for(const row of rows){const show=(!desk.value||row.dataset.category===desk.value)&&row.cells[0].textContent.toUpperCase().includes(symbol.value.trim().toUpperCase());row.hidden=!show;if(show)n++;}count.textContent=n+' of '+rows.length+' visible';}desk.addEventListener('change',filter);symbol.addEventListener('input',filter);filter();})();</script>
</body></html>'''
