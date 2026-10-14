"""Presentation-only export of an existing verified historical baseline.

The original bundle and frozen experiment are never edited. The exported copy
retains the exact old report, evidence and verification interface, with a new
static dashboard beside them. No providers, inference, orders or new trials.
"""
from __future__ import annotations

import argparse
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from html import escape
import json
from pathlib import Path
import sys

from .contracts.mission_request import parse_strict_json_object_bytes
from .decision_journal_store import JournalStoreError, check_separate_root
from .desk_candidate_review_cli import _write
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import read_regular
from .shadow_historical_baseline_cli import _output_root, verify_bundle


def _text(value):
    return escape(str(value), quote=True)


def _number(value):
    if value is None:
        return None
    number = Decimal(value)
    if not number.is_finite():
        raise ValueError("display requires finite retained values")
    return number


def _percent(value, unit="%"):
    number = _number(value)
    if number is None:
        return "—"
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        amount = number * 100
        rendered = format(amount, ".4f")
        if amount != 0 and Decimal(rendered) == 0:
            rendered = format(amount, ".2E")
        return _text(rendered) + unit


def _chart(summary):
    values = [_number(summary[field]) for field in ("mean_gross_return", "mean_control_gross_return")]
    if any(value is None for value in values):
        return '<div class="empty">No paired comparison available. Missing values are not zero returns.</div>'
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        low, high = min(Decimal(0), *values), max(Decimal(0), *values)
        if low == high:
            low, high = Decimal("-0.001"), Decimal("0.001")
        else:
            padding = (high - low) / 8
            low = low - padding if low < 0 else low
            high = high + padding if high > 0 else high
        def x(value):
            return Decimal(150) + (value - low) / (high - low) * 390
        zero = x(Decimal(0))
        svg = ['<svg role="img" aria-label="Rule versus control: average gross price change per observation" viewBox="0 0 760 230"><title>Rule versus control</title><desc>Two bars share the same scale and zero baseline. Values are average gross price changes per paired observation, before costs; they are not account returns.</desc>']
        svg.append('<line class="zero" x1="{0:.3f}" x2="{0:.3f}" y1="30" y2="170"/>'.format(zero))
        for index, (name, key, value) in enumerate(zip(("Rule", "Control"), ("rule", "control"), values)):
            y = 65 + index * 75
            start, width = min(zero, x(value)), abs(x(value) - zero)
            svg.append(f'<text x="0" y="{y + 7}">{name}</text><rect data-series="{key}" data-value="{_text(value)}" class="{key}" x="{start:.3f}" y="{y - 16}" width="{width:.3f}" height="32" rx="3"/><text class="value" x="750" y="{y + 7}" text-anchor="end">{_percent(value)}</text>')
        svg.append('<text class="tick" x="{0:.3f}" y="202" text-anchor="middle">0%</text>'.format(zero))
        svg.append('<text class="tick" x="150" y="225">' + _percent(low) + '</text><text class="tick" x="540" y="225" text-anchor="end">' + _percent(high) + '</text></svg>')
        return "".join(svg)


def render_historical_dashboard(report):
    """Format retained values only; no signal, benchmark or research recomputation."""
    summary = report["summary"]
    rule, gap = (_number(summary[key]) for key in ("mean_gross_return", "mean_gross_excess_over_control"))
    if rule is None or gap is None or summary["mean_control_gross_return"] is None:
        title = "Comparison unavailable."
        explanation = "There is not enough paired evidence to compare the rule with its control."
    elif gap < 0:
        title = "No advantage over the control."
        explanation = "The rule did not beat the benchmark in this historical sample, even before costs. These results do not demonstrate a trading edge."
    elif gap == 0:
        title = "Rule and control tied before costs."
        explanation = "The rule added no average gross advantage over the benchmark in this historical sample."
    elif rule <= 0:
        title = "Ahead of control, but the rule average was not positive."
        explanation = "A smaller loss than the control does not satisfy the frozen requirement for a positive rule average."
    else:
        title = "Rule ahead before costs."
        explanation = "The gross comparison was positive in this historical sample. This does not establish statistical significance, net profitability or trading authority."
    coverage = "; ".join(_text(row["symbol"]) + ": " + _text(row["source_first_date"]) + " through " + _text(row["source_last_date"])
                         for row in report["source_coverage"])
    return """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BlackPod · Historical baseline</title><style>
*{box-sizing:border-box}body{margin:0;padding:clamp(18px,4vw,44px);background:#0d1922;color:#e5edf2;font:16px/1.55 system-ui,sans-serif}main{max-width:1000px;margin:auto}nav{display:flex;justify-content:space-between;gap:16px;font-size:.8rem;margin-bottom:30px;color:#a9bdcb}a{color:#b3dce9;text-underline-offset:4px}h1{font-size:clamp(1.8rem,5vw,2.8rem);letter-spacing:-.04em;line-height:1.15;margin:.4rem 0}h2{font-size:1.15rem;letter-spacing:-.02em}p{max-width:74ch}.eyebrow{color:#a8c8bc;letter-spacing:.1em;text-transform:uppercase;font-size:.68rem;font-weight:700}.lead{color:#b6cad7}.result,section,details{padding:clamp(18px,3vw,28px);border:1px solid #334f5e;background:#142630;border-radius:10px;margin:22px 0}.result{border-left:4px solid #d0b17b}.result h2{font-size:1.5rem;line-height:1.3;margin:0 0 .5rem}.result p{margin:.4rem 0;color:#c5d7e2}.numbers{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px;margin:22px 0 0}.numbers dt{font-size:.75rem;color:#acc2d0}.numbers dd{margin:.25rem 0;font-size:1.6rem;letter-spacing:-.04em;font-variant-numeric:tabular-nums}svg{display:block;width:100%;height:auto;margin:12px 0}svg text{fill:#dce9ef;font:18px system-ui,sans-serif}.value{font-size:19px;font-weight:600}.tick{fill:#9fb7c7;font-size:12px}.zero{stroke:#92adbd;stroke-width:1}.rule{fill:#72bca8}.control{fill:#8da9c6}.caption{color:#a8c0ce;font-size:.8rem}.definition{font-size:.9rem;color:#c6d8e3}.empty{padding:30px 15px;text-align:center;color:#b6cad7;border-block:1px dashed #58717f}.facts{display:flex;flex-wrap:wrap;gap:12px 36px;border-top:1px solid #304b59;padding-top:16px;font-size:.8rem;color:#b3c8d5}.facts strong{color:#e1ecf2}summary{cursor:pointer;font-weight:600}a:focus-visible,summary:focus-visible{outline:3px solid #b7dfef;outline-offset:5px}li{margin:.7rem 0}code{font-size:.8em;overflow-wrap:anywhere}.links{display:flex;flex-wrap:wrap;gap:12px 24px}.scope{font-size:.8rem;color:#cbb58e}@media(max-width:550px){.numbers{grid-template-columns:1fr;gap:10px}.numbers>div{display:flex;align-items:center;justify-content:space-between;gap:12px}.numbers dd{font-size:1.2rem}svg text{font-size:22px}svg .tick{font-size:15px}nav{flex-wrap:wrap}}
</style></head><body><main><nav><a href="http://127.0.0.1:5181/?view=research">Forward experiment</a><span>Read-only · historical evidence</span></nav>
<header><p class="eyebrow">Past data · same frozen rule</p><h1>Historical baseline</h1><p class="lead">Did a down-day reversal rule add anything beyond the market comparison?</p></header>
<div class="result"><h2>""" + _text(title) + "</h2><p>" + _text(explanation) + """</p></div>
<section aria-labelledby="comparison-heading"><p class="eyebrow">Same dates · same gross exposure · before costs</p><h2 id="comparison-heading">Rule versus control</h2>
""" + _chart(summary) + """<p class="definition"><strong>Rule:</strong> check each ETF independently after a down close; measure next open → following session’s open.<br><strong>Control:</strong> equal parts QQQ + SPY over the identical dates.</p>
<dl class="numbers"><div><dt>Rule average</dt><dd>""" + _percent(summary["mean_gross_return"]) + "</dd></div><div><dt>Control average</dt><dd>" + _percent(summary["mean_control_gross_return"]) + "</dd></div><div><dt>Difference</dt><dd>" + _percent(summary["mean_gross_excess_over_control"], " pp") + """</dd></div></dl>
<p class="caption">pp = percentage points. Averages are per measured price window, not annual returns or account profit. The chart uses a common zero baseline.</p>
<div class="facts"><span><strong>""" + _text(format(summary["paired_candidate_count"], ",")) + "</strong> paired observations</span><span>Scored through <strong>" + _text(report["cutoff"]) + "</strong></span><span><strong>" + _text(summary["unpaired_candidate_count"]) + """</strong> unpaired candidates retained</span></div></section>
<section><h2>What this means</h2><p>A rule can go up and still add no value if the control does just as well. The relevant question is how much it adds over the same-date comparison.</p>
<p class="scope">Costs and execution are unmeasured. Historical Yahoo prices and the forward test’s IEX prices are not verified equivalent. Price adjustments remain unverified.</p>
<p class="caption">The forward experiment stays frozen. New forward observations remain separate; historical results never populate them. No trades, tuning or automatic promotion follow from this page.</p><p class="caption">Research record: auto-trading OFF. This page has no execution controls.</p></section>
<details><summary>Data, original report &amp; limitations</summary><p>Retained source coverage: """ + coverage + """. All scored prices stop at the protected cutoff. Later reserved research data remains unscored. Missing evidence and every original observation remain retained.</p>
<p class="links"><a href="report.html">Original detailed report</a><a href="report.json">Full JSON results</a><a href="rows.csv">All observations · CSV</a><a href="cohorts.json">30-session historical blocks</a><a href="bundle-manifest.json">Original evidence hashes</a><a href="dashboard-manifest.json">Dashboard source binding</a></p>
<p class="caption">This is a new presentation of the existing verified report, not another backtest or an additional independent trial. The original report and source bytes are unchanged. Local hashes verify retained bytes, not provider truth. Observations are correlated; no significance or future success probability is inferred.</p>
<p>Source report: <code>""" + _text(report["report_id"]) + "</code></p></details></main></body></html>"


def export_dashboard(baseline_root: Path, output_root: Path):
    """Mirror verified evidence, then publish a separate immutable presentation."""
    baseline_root, output_root = _output_root(baseline_root), _output_root(output_root)
    check_separate_root(output_root, baseline_root)
    manifest_raw = read_regular(baseline_root / "bundle-manifest.json", max_bytes=1024 * 1024)
    verified = verify_bundle(baseline_root)
    if manifest_raw != read_regular(baseline_root / "bundle-manifest.json", max_bytes=1024 * 1024):
        raise ValueError("source manifest changed during verification")
    manifest = parse_strict_json_object_bytes(manifest_raw)
    files = {"bundle-manifest.json": manifest_raw}
    for ref in manifest["files"]:
        raw = read_regular(baseline_root / ref["path"], max_bytes=64 * 1024 * 1024)
        if sha256_bytes(raw) != ref["sha256"] or len(raw) != ref["size_bytes"]:
            raise ValueError("verified source changed during export")
        files[ref["path"]] = raw
    report = parse_strict_json_object_bytes(files["report.json"])
    if report["report_id"] != verified["report_id"]:
        raise ValueError("dashboard source report identity differs")
    files["dashboard.html"] = render_historical_dashboard(report).encode()
    files["dashboard-source.py"] = read_regular(Path(__file__))
    dashboard = {"schema_version": "blackpod.shadow_historical_dashboard.v1",
        "scope": "PRESENTATION_ONLY_NO_NEW_RESEARCH_TRIAL", "source_report_id": verified["report_id"],
        "source_bundle_manifest_sha256": sha256_bytes(manifest_raw),
        "files": [{"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)} for path, raw in sorted(files.items())]}
    written = not (output_root / "dashboard-manifest.json").exists()
    for path, raw in sorted(files.items()):
        _write(output_root / path, raw, (baseline_root,))
    _write(output_root / "dashboard-manifest.json", canonical_json_bytes(dashboard), (baseline_root,))
    verify_bundle(output_root)
    return {"written": written, "output_root": str(output_root), "source_report_id": verified["report_id"],
        "dashboard_sha256": sha256_bytes(files["dashboard.html"]), "provider_calls": 0,
        "auto_trading_changed": False, "experiment_changed": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Presentation of a verified historical baseline; no new research or providers")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("--baseline-root", type=Path, required=True)
    export.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(export_dashboard(args.baseline_root, args.output_root), sort_keys=True))
        return 0
    except (ValueError, OSError, TypeError, KeyError, JournalStoreError):
        print("historical-dashboard: rejected; check verified source, separate output and immutable identities", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
