"""Plain, standalone historical baseline report. No provider or UI controls."""
from decimal import Decimal, Context, ROUND_HALF_EVEN, localcontext
from html import escape


def _text(value):
    return escape(str(value))


def _percent(value):
    if value is None:
        return "Unavailable"
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        return _text(format(Decimal(value) * 100, ".4f")) + "%"


def _label(value):
    return _text(value.replace("_", " ").lower())


def render_historical_baseline(material):
    report, cohorts = material["report"], material["cohorts"]
    summary, cohort_summary = report["summary"], report["cohort_summary"]
    body = ["""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BlackPod historical reversal baseline</title><style>
*{box-sizing:border-box}body{margin:0;padding:clamp(16px,4vw,48px);background:#101a21;color:#e3eaf0;font:16px/1.6 system-ui,sans-serif}main{max-width:1180px;margin:auto}h1{line-height:1.2}h2{font-size:1.3rem}a{color:#afd6ec}header,section{padding:24px;border:1px solid #3c5665;border-radius:7px;margin:20px 0;background:#15242e}.eyebrow{color:#b4d7cb;text-transform:uppercase;letter-spacing:.06em;font-size:.8rem}.limit{border-left:3px solid #c8b17e;padding:12px 18px;background:#26333a}.cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.cards>div{padding:16px;background:#1e3441;border:1px solid #3c5665}.cards strong{display:block;font-size:1.65rem}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;min-width:650px;font-size:.9rem}th,td{padding:12px;text-align:left;border-bottom:1px solid #3c5665;vertical-align:top}th{background:#1e3441}code{overflow-wrap:anywhere;font-size:.82em}dt{font-weight:600}dd{margin:0 0 12px}summary{cursor:pointer}li{margin:6px 0}@media(max-width:650px){.cards{grid-template-columns:1fr}header,section{padding:16px}}
</style><main><header><p class="eyebrow">Trading research · retrospective context · auto-trading OFF</p><h1>Historical reversal baseline</h1>
<p>One fixed rule: after a down close, observe the next session’s opening price to the following session’s opening price. QQQ and SPY; no strategy tuning.</p></header>
<p class="limit"><strong>Historical context, not a promise.</strong> These Yahoo price responses are not verified as comparable to the prospective IEX bars. Adjustments, corporate actions, publication timing and costs remain unqualified. Net returns, account P&amp;L and economic support are unavailable. The live pilot and its thresholds are unchanged.</p>"""]
    body.append("<section><h2>What was measured</h2><dl><dt>Retained calendar range</dt><dd>" + _text(report["first_signal_session"]) + " through " + _text(report["last_signal_session"]) + "</dd>")
    body.append("<dt>Joint 30-session block anchor</dt><dd>" + _text(report["cohort_anchor"]) + " · QQQ did not exist in the 1998 portion.</dd><dt>Protected research cutoff</dt><dd>Every scored signal, entry and exit is on or before " + _text(report["cutoff"]) + ". The existing embargo and holdout remain unscored.</dd></dl>")
    body.append("<div class='cards'><div>Calendar opportunities<strong>" + _text(summary["opportunity_count"]) + "</strong></div><div>Candidate responses with matched control<strong>" + _text(summary["paired_candidate_count"]) + "</strong></div><div>Unpaired candidates retained<strong>" + _text(summary["unpaired_candidate_count"]) + "</strong></div></div>")
    body.append("<p>Mean returns below use only candidate observations with both QQQ and SPY prices on the identical entry and exit dates. Every other opportunity remains in the downloadable rows. The cash benchmark assumes zero interest.</p></section>")
    body.append("<section><h2>Full historical paired comparison</h2><div class='cards'>")
    for title, field in (("Mean candidate gross response", "mean_gross_return"), ("Mean matched-control response", "mean_control_gross_return"), ("Mean gross excess over control", "mean_gross_excess_over_control")):
        body.append("<div>" + title + "<strong>" + _percent(summary[field]) + "</strong></div>")
    body.append("</div><p>Positive candidate response fraction: <strong>" + _percent(summary["positive_gross_outcome_fraction"]) + "</strong>. A positive response is a price observation, not a profitable executed trade. Comparing only winners or win rate can hide larger losses.</p>")
    body.append("<p>When both symbols qualify on the same dates, their average equals the equal-weight control. Excess over the control chiefly measures which symbol is selected on the other dates.</p></section>")
    body.append("<section><h2>Variation across fixed 30-session blocks</h2><p>These blocks match the live pilot’s session count. Their starts were fixed from the first joint lookback date; no start date or threshold was optimized. Blocks and adjacent observations are correlated.</p>")
    body.append("<p>" + _text(cohort_summary["cohort_count"]) + " total blocks; " + _text(cohort_summary["distribution_cohort_count"]) + " complete blocks with no missing evidence and at least 12 paired candidates enter the descriptive quantiles. All excluded and incomplete blocks remain listed below.</p>")
    body.append("<div class='scroll'><table><thead><tr><th>Historical block measure</th><th>10th percentile</th><th>Median</th><th>90th percentile</th></tr></thead><tbody>")
    for field, title in (("mean_gross_return", "Mean candidate response"), ("mean_gross_excess_over_control", "Mean excess over control"), ("paired_candidate_count", "Paired candidate count")):
        values = cohort_summary["quantiles"][field]
        fmt = (lambda item: "Unavailable" if item is None else _text(item)) if field.endswith("count") else _percent
        body.append("<tr><th>" + title + "</th>" + "".join("<td>" + fmt(values[key]) + "</td>" for key in ("p10", "p50", "p90")) + "</tr>")
    body.append("</tbody></table></div><p class='limit'>These are ranks of past blocks, not confidence intervals or a forecast that the next block will fall inside them. They do not change the live experiment’s frozen success criteria.</p><ul>")
    for key, value in cohort_summary["conclusion_counts"].items():
        body.append("<li>" + _label(key) + ": " + _text(value) + "</li>")
    body.append("</ul></section>")
    for title, rows, key in (("Per-symbol comparison", report["per_symbol"], "symbol"), ("Calendar-year comparison", report["per_year"], "year")):
        body.append("<section><h2>" + title + "</h2><div class='scroll'><table><thead><tr><th>" + key.title() + "</th><th>Paired / candidates</th><th>Candidate gross mean</th><th>Control mean</th><th>Excess mean</th></tr></thead><tbody>")
        for row in rows:
            body.append("<tr><th>" + _text(row[key]) + "</th><td>" + _text(row["paired_candidate_count"]) + " / " + _text(row["candidate_count"]) + "</td>" + "".join("<td>" + _percent(row[field]) + "</td>" for field in ("mean_gross_return", "mean_control_gross_return", "mean_gross_excess_over_control")) + "</tr>")
        body.append("</tbody></table></div></section>")
    body.append("<section><h2>Sources and reproducibility</h2><ul>")
    for row in report["source_coverage"]:
        body.append("<li>" + _text(row["symbol"]) + ": " + _text(row["source_row_count"]) + " retained rows, " + _text(row["source_first_date"]) + " through " + _text(row["source_last_date"]) + "; " + _text(row["scored_source_row_count"]) + " price rows within the cutoff. Price basis UNKNOWN; adjusted close was not used to modify opens.</li>")
    body.append("</ul><p><a href='report.json'>Full JSON report</a> · <a href='rows.csv'>Every opportunity as CSV</a> · <a href='cohorts.json'>Every 30-session block</a> · <a href='bundle-manifest.json'>Retained-file hashes</a></p><p>Report identity: <code>" + _text(report["report_id"]) + "</code></p><details><summary>Limitations and interpretation</summary><ul>")
    for reason in report["limitations"]:
        body.append("<li><code>" + _text(reason) + "</code></li>")
    body.append("</ul></details><details><summary>All fixed blocks</summary><div class='scroll'><table><thead><tr><th>Block</th><th>Signal sessions</th><th>Paired candidates</th><th>Gross mean</th><th>Excess mean</th><th>Conclusion</th></tr></thead><tbody>")
    for row in cohorts:
        body.append("<tr><td>" + _text(row["cohort_index"]) + "</td><td>" + _text(row["first_signal_session"]) + " to " + _text(row["last_signal_session"]) + "</td><td>" + _text(row["paired_candidate_count"]) + "</td><td>" + _percent(row["mean_gross_return"]) + "</td><td>" + _percent(row["mean_gross_excess_over_control"]) + "</td><td>" + _label(row["conclusion"]) + "</td></tr>")
    body.append("</tbody></table></div></details></section></main></html>")
    return "".join(body)
