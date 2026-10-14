import { useState } from "react";
import type { ShadowOutcome, ShadowPrediction } from "../contracts/shadowExperiment";
import { useShadowExperiment } from "../data/useShadowExperiment";
import "./shadow-experiment.css";

const percent = (value: string | null, unit = "%") => value === null ? "—" : `${(Number(value) * 100).toLocaleString("en-US", { maximumFractionDigits: 3, minimumFractionDigits: 2 })}${unit}`;
const stamp = (value: string) => new Date(value).toLocaleString("en-US", { timeZone: "America/Los_Angeles", year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" });
const label = (value: string) => value.toLowerCase().replaceAll("_", " ");
const shortDate = (value: string) => new Date(`${value}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric" });
const statuses: Record<string, { name: string; mark: string; tone: string }> = {
  OBSERVATIONAL_CANDIDATE: { name: "Candidate", mark: "C", tone: "candidate" },
  ABSTAIN_NONNEGATIVE_RETURN: { name: "Abstained", mark: "–", tone: "abstained" },
  ABSTAIN_OVERLAP: { name: "Abstained", mark: "–", tone: "abstained" },
  DEFER_MISSING_INPUT: { name: "Missing input", mark: "!", tone: "missing" },
  MISSED_PREDICTION_DEADLINE: { name: "Missed deadline", mark: "M", tone: "missed" },
};
const waiting = { name: "Awaiting prediction", mark: "·", tone: "waiting" };

function reportLink(value: string | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "http:" && ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}

function OutcomeCell({ outcome, prediction }: { outcome: ShadowOutcome | undefined; prediction: ShadowPrediction | undefined }) {
  if (!prediction) return <>Not recorded</>;
  if (!outcome) return prediction.status === "OBSERVATIONAL_CANDIDATE" ? <>Waiting for outcome</> : <>No outcome recorded</>;
  return <><strong>{label(outcome.status)}</strong>{outcome.candidate_gross_return !== null ? <>
    <span>Candidate {percent(outcome.candidate_gross_return)}</span><span>Control {percent(outcome.control_gross_return)}</span>
    <span>Excess {percent(outcome.excess_over_control, " pp")}</span><span>Cash {percent(outcome.cash_return)}</span>
  </> : null}</>;
}

function DifferenceGraphic({ value }: { value: string | null }) {
  if (value === null) return <div className="experiment-chart-empty"><span aria-hidden="true">—</span><p>Waiting for measured outcomes</p></div>;
  // Position a saved result for display only; no research results are calculated here.
  const amount = Number(value) * 100, bound = Math.max(0.1, Math.abs(amount)), offset = Math.abs(amount) / bound * 43;
  return <div className="experiment-difference" role="img" aria-label={`Mean gross difference versus control: ${percent(value, " pp")}`}>
    <div className="experiment-axis-labels"><span>Control ahead</span><span>Rule ahead</span></div>
    <div className="experiment-axis"><span className="experiment-zero" /><span className={`experiment-difference-bar ${amount < 0 ? "negative" : "positive"}`} style={{ left: `${amount < 0 ? 50 - offset : 50}%`, width: `${offset}%` }} />
      <span className="experiment-marker" style={{ left: `${50 + (amount < 0 ? -offset : offset)}%` }} /></div>
    <div className="experiment-axis-labels"><span>{percent(String(-bound / 100), " pp")}</span><span>0 pp · control</span><span>{percent(String(bound / 100), " pp")}</span></div>
  </div>;
}

/** Only presentation changes: recorded predictions, outcomes and research criteria stay intact. */
export function ShadowExperiment({ enabled = true, historicalReportUrl = import.meta.env.VITE_SHADOW_HISTORICAL_REPORT_URL }: { enabled?: boolean; historicalReportUrl?: string }) {
  const state = useShadowExperiment({ enabled });
  const [showAll, setShowAll] = useState(false);
  const feed = state.feed, view = feed?.experiment, protocol = view?.protocol, summary = view?.summary;
  const predictions = new Map(view?.predictions.map((row) => [`${row.signal_session}:${row.symbol}`, row]));
  const outcomes = new Map(view?.outcomes.map((row) => [row.prediction_id, row]));
  const historyUrl = reportLink(historicalReportUrl);
  const conclusion = summary?.conclusion === "PENDING" ? "Collecting evidence" : summary?.conclusion.startsWith("INCONCLUSIVE") ? "Inconclusive" : summary?.conclusion === "DESCRIPTIVE_POSITIVE_PROXY_ONLY" ? "Positive gross comparison" : "Rule did not clear the comparison";
  return <article className="shadow-experiment" aria-label="Read-only shadow experiment">
    <header className="experiment-banner"><div><p className="experiment-eyebrow">Trading research <span>Shadow only</span></p>
      <h1>Reversal experiment</h1><p>After a down day, does this rule beat the control?</p></div>
      <button type="button" onClick={state.refresh} disabled={!enabled || state.refreshing}>{state.refreshing ? "Reading records…" : "Refresh saved records"}</button>
    </header>
    <p className="experiment-boundary"><strong>No trading authority.</strong> Saved evidence only. No orders or account P&amp;L.</p>
    {state.status !== "READY" ? <section className="experiment-alert" role="status"><h2>{state.status === "LOADING" ? "Reading the experiment…" : state.status === "NOT_CONFIGURED" ? "No experiment configured" : state.status === "DISABLED" ? "Reading paused" : "Experiment unavailable"}</h2>
      <p>{state.message}</p>{state.status === "NOT_CONFIGURED" ? <p>Start the local reader with an explicit <code>SHADOW_EXPERIMENT_ROOT</code>. No fixture or historical prediction set is substituted.</p> : null}</section> : null}
    {view && protocol && summary && feed ? <>
      <ol className="experiment-steps" aria-label="How this test works"><li><span>1</span><div>Observe<strong>Each ETF: down day?</strong></div></li>
        <li><span>2</span><div>Record<strong>Candidate or abstention</strong></div></li><li><span>3</span><div>Measure<strong>Next open → following open</strong></div></li></ol>
      <section aria-labelledby="experiment-progress-heading"><div className="experiment-section-heading"><div><p className="experiment-eyebrow">New observations · forward test</p><h2 id="experiment-progress-heading">30 sessions. One fixed test.</h2></div>
        <span className="experiment-tag">{conclusion}</span></div>
        <dl className="experiment-counts"><div><dt>Predictions recorded</dt><dd>{summary.recorded_prediction_count} / {summary.opportunity_count}</dd></div>
          <div><dt>Candidates</dt><dd>{summary.candidate_count}</dd></div><div><dt>Measured outcomes</dt><dd>{summary.observed_outcome_count}</dd></div></dl>
        <div className="experiment-session-grid" role="region" aria-label="30-session progress">{protocol.sessions.map((session) => <div className="experiment-day" key={session.date}>
          <span className="experiment-day-date">{shortDate(session.date)}</span><div>{protocol.universe.map((symbol) => {
            const prediction = predictions.get(`${session.date}:${symbol}`), status = prediction ? statuses[prediction.status] : waiting;
            const name = `${session.date} ${symbol}: ${status.name}`;
            return <span key={symbol} role="img" aria-label={name} title={name} className={`experiment-check ${status.tone}`}>{status.mark}</span>;
          })}</div></div>)}</div>
        <ul className="experiment-legend" aria-label="Progress key"><li><span className="experiment-check waiting">·</span>Waiting</li><li><span className="experiment-check candidate">C</span>Candidate</li>
          <li><span className="experiment-check abstained">–</span>Abstained</li><li><span className="experiment-check missing">!</span>Missing input</li><li><span className="experiment-check missed">M</span>Missed deadline</li></ul>
        <p className="experiment-caption">Each date has two checks: QQQ, then SPY. {shortDate(protocol.sessions[0].date)}–{shortDate(protocol.sessions.at(-1)!.date)}. Empty checks are planned observations, not results.</p>
        {summary.missed_count + summary.missing_input_count > 0 ? <p className="experiment-data-warning" role="status">Evidence gaps: {summary.missed_count} missed deadlines · {summary.missing_input_count} missing inputs. These stay in the experiment.</p> : null}
        <p className="experiment-clock">Last market evidence: <strong>{view.latest_captured_at ? stamp(view.latest_captured_at) : "None recorded"}</strong></p>
      </section>
      <div className="experiment-comparison-layout">
        <section aria-labelledby="experiment-comparison-heading"><p className="experiment-eyebrow">Forward result · before costs</p><h2 id="experiment-comparison-heading">Did the rule beat the control?</h2>
          <dl className="experiment-result-numbers"><div><dt>Rule average</dt><dd>{percent(summary.mean_gross_return)}</dd></div><div><dt>Difference vs control</dt><dd>{percent(summary.mean_gross_excess_over_control, " pp")}</dd></div></dl>
          <DifferenceGraphic value={summary.mean_gross_excess_over_control} />
          <p className="experiment-caption">Control = equal parts QQQ + SPY over the same dates. pp = percentage points. These are price changes, before costs.</p>
        </section>
        <section className="experiment-history" aria-labelledby="experiment-history-heading"><p className="experiment-eyebrow">Old observations · backtest</p><h2 id="experiment-history-heading">Historical baseline</h2>
          <div className="experiment-history-symbol" aria-hidden="true">↶</div><p>The same rule replayed on old prices. A separate reference for what to expect.</p>
          {historyUrl ? <a href={historyUrl} target="_blank" rel="noopener noreferrer">Open historical report <span aria-hidden="true">↗</span></a> : <p className="experiment-caption">Report link not configured.</p>}
          <p className="experiment-caption">Historical results never fill the forward test’s empty checks. Different data sources limit direct comparisons.</p>
        </section>
      </div>
      <section aria-labelledby="experiment-observations-heading"><div className="experiment-section-heading"><h2 id="experiment-observations-heading">Recorded predictions</h2>
        <label className="experiment-filter"><input type="checkbox" checked={showAll} onChange={(event) => setShowAll(event.target.checked)} />Show all 60 scheduled checks</label></div>
        {!showAll && view.predictions.length === 0 ? <p className="experiment-empty">No predictions recorded yet.<span>The collector must wait for completed session data.</span></p> : <div className="experiment-table-scroll" role="region" aria-label="Experiment predictions and outcomes" tabIndex={0}><table><caption>Saved predictions and linked outcomes · gross price changes</caption>
          <thead><tr><th scope="col">Date / symbol</th><th scope="col">Prediction</th><th scope="col">Down-day signal</th><th scope="col">Entry → exit</th><th scope="col">Outcome / control</th><th scope="col">Evidence</th></tr></thead>
          <tbody>{protocol.sessions.flatMap((session) => protocol.universe.flatMap((symbol) => {
            const row = predictions.get(`${session.date}:${symbol}`), outcome = row && outcomes.get(row.prediction_id);
            if (!showAll && !row) return [];
            return <tr key={`${session.date}:${symbol}`}><th scope="row">{session.date}<span>{symbol}</span></th>
              <td>{row ? <><strong>{statuses[row.status].name}</strong><small>Recorded {stamp(row.recorded_at)}</small></> : "Awaiting prediction"}</td>
              <td>{percent(row?.signal_return ?? null)}</td><td>{row ? <>{row.entry_session}<span>→ {row.exit_session}</span></> : "Not recorded"}</td>
              <td><OutcomeCell outcome={outcome} prediction={row} /></td><td>{row ? <details><summary>Source &amp; reasons</summary><p>{label(row.status)}</p>
                <ul>{[...row.reason_codes, ...(outcome?.reason_codes ?? [])].map((reason, index) => <li key={index}><code>{reason}</code></li>)}</ul>
                <code>{row.prediction_id}</code>{outcome ? <code>{outcome.outcome_id}</code> : null}</details> : "No record yet"}</td></tr>;
          }))}</tbody></table></div>}
        <p className="experiment-caption">Candidate = observe the rule. Abstained = no candidate. Neither is a trade order.</p>
      </section>
      <details className="experiment-method"><summary>Rules &amp; evidence</summary>
        <h2>Frozen protocol</h2><p>A completed negative provider close-to-close change records a candidate; otherwise abstain. Observe the next daily-bar open to the following session’s daily-bar open. The first eligible capture seals the prediction, including missing inputs. Later evidence cannot upgrade it.</p>
        <dl className="experiment-facts"><div><dt>Experiment</dt><dd><code>{protocol.experiment_id}</code></dd></div><div><dt>Protocol frozen</dt><dd>{stamp(protocol.frozen_at)}</dd></div>
          <div><dt>Signal sessions</dt><dd>{protocol.sessions[0].date} through {protocol.sessions.at(-1)!.date} · 30 sessions / 60 symbol opportunities</dd></div>
          <div><dt>Reader checked</dt><dd>{stamp(feed.checked_at)} · reading the page does not refresh market evidence</dd></div>
          <div><dt>Current conclusion</dt><dd>{label(summary.conclusion)}</dd></div>
          <div><dt>Waiting / abstained</dt><dd>{summary.pending_prediction_count} / {summary.abstention_count}</dd></div>
          <div><dt>Missed / missing input</dt><dd>{summary.missed_count} / {summary.missing_input_count}</dd></div>
          <div><dt>Observed / pending outcomes</dt><dd>{summary.observed_outcome_count} / {summary.pending_outcome_count}</dd></div>
          <div><dt>Positive gross outcome fraction</dt><dd>{percent(summary.positive_gross_outcome_fraction)}</dd></div></dl>
        <h2>Fixed comparisons</h2><ul><li>Control: equal-weight QQQ/SPY opening-price return, identical dates and unit gross exposure. Cash: zero return, no interest.</li>
          <li>Inputs wait until 15 minutes after the extended session closes. Record at least five minutes before the next extended-session open.</li>
          <li>At least 12 observed candidates is an operational minimum, not a statistical power calculation. Missing, late, abstained and pending records remain visible.</li>
          <li>Both mean candidate gross return and mean gross excess must be strictly positive. Incomplete evidence is inconclusive. No tuning, automatic extension or promotion; review manually.</li></ul>
        <p>No net performance or realized trade P&amp;L is calculated. Fees, slippage, capacity, continuity, risk and uncertainty remain unqualified. QQQ, SPY and adjacent sessions are correlated; no statistical significance or economic edge is inferred.</p>
        <p>IEX daily bars are observational proxies, not verified regular-session opening auctions or fills. Their basis differs from the original hypothesis. Displayed percentages round to three decimals; recorded values are unchanged.</p>
        <h2>Journal integrity</h2><dl className="experiment-facts"><div><dt>Verified local journal</dt><dd>{view.journal.event_count} events · {view.journal.evidence_blob_count} retained blobs</dd></div>
          <div><dt>Journal head</dt><dd><code>{view.journal.last_entry_sha256}</code></dd></div><div><dt>Method</dt><dd><code>{protocol.method_version}</code></dd></div>
          <div><dt>Original hypothesis</dt><dd><code>{protocol.original_hypothesis_id}</code></dd></div></dl>
        <p>Local clocks and receipts do not independently authenticate preregistration. Hashes verify retained bytes, not provider truth or completeness.</p>
        <ul>{view.limitations.map((reason) => <li key={reason}><code>{reason}</code></li>)}</ul>
      </details>
    </> : null}
  </article>;
}

export function ShadowExperimentPage() {
  return <main className="shadow-experiment-page"><div className="experiment-page-inner"><nav aria-label="Research view navigation"><a href="/">Return to Captain’s Cabin</a><span>Read-only experiment</span></nav><ShadowExperiment /></div></main>;
}
