import type { ShadowOutcome, ShadowPrediction } from "../contracts/shadowExperiment";
import { useShadowExperiment } from "../data/useShadowExperiment";
import "./shadow-experiment.css";

const percent = (value: string | null) => value === null ? "Unavailable" : `${(Number(value) * 100).toLocaleString("en-US", { maximumFractionDigits: 3, minimumFractionDigits: 2 })}%`;
const stamp = (value: string) => new Date(value).toLocaleString("en-US", { timeZone: "UTC", year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }) + " UTC";
const label = (value: string) => value.toLowerCase().replaceAll("_", " ");

function OutcomeCell({ outcome, prediction }: { outcome: ShadowOutcome | undefined; prediction: ShadowPrediction | undefined }) {
  if (!prediction) return <>Not recorded</>;
  if (!outcome) return <>Pending / not recorded</>;
  return <><strong>{label(outcome.status)}</strong><span>Candidate {percent(outcome.candidate_gross_return)}</span>
    <span>Control {percent(outcome.control_gross_return)}</span><span>Excess {percent(outcome.excess_over_control)}</span>
    <span>Cash {percent(outcome.cash_return)}</span></>;
}

/** Present one recorded pilot; all calculation and evidence validation stays on the read side. */
export function ShadowExperiment({ enabled = true }: { enabled?: boolean }) {
  const state = useShadowExperiment({ enabled });
  const feed = state.feed, view = feed?.experiment, protocol = view?.protocol, summary = view?.summary;
  const predictions = new Map(view?.predictions.map((row) => [`${row.signal_session}:${row.symbol}`, row]));
  const outcomes = new Map(view?.outcomes.map((row) => [row.prediction_id, row]));
  return <article className="shadow-experiment" aria-label="Read-only shadow experiment">
    <header className="experiment-banner"><div><p className="experiment-eyebrow">Trading research · observation only</p>
      <h1>One hypothesis. One frozen experiment.</h1><p>Previous-session reversal · QQQ and SPY · one-session gross price proxy.</p></div>
      <button type="button" onClick={state.refresh} disabled={!enabled || state.refreshing}>{state.refreshing ? "Reading records…" : "Refresh saved records"}</button>
    </header>
    <p className="experiment-boundary"><strong>No trading authority.</strong> This page reads saved evidence. It does not collect market data, generate predictions, evaluate outcomes, or enable auto-trading.</p>
    {state.status !== "READY" ? <section className="experiment-alert" role="status"><h2>{state.status === "LOADING" ? "Reading the experiment…" : state.status === "NOT_CONFIGURED" ? "No experiment configured" : state.status === "DISABLED" ? "Reading paused" : "Experiment unavailable"}</h2>
      <p>{state.message}</p>{state.status === "NOT_CONFIGURED" ? <p>Start the local reader with an explicit <code>SHADOW_EXPERIMENT_ROOT</code>. No fixture or historical prediction set is substituted.</p> : null}</section> : null}
    {view && protocol && summary && feed ? <>
      <section aria-labelledby="experiment-protocol-heading"><div className="experiment-section-heading"><h2 id="experiment-protocol-heading">Frozen protocol</h2><span className="experiment-tag">Prospective shadow pilot</span></div>
        <p>After a completed provider close-to-close decline, record a candidate before the next declared extended session opens. Observe its provider opening-price change over one session. Otherwise record the abstention or missing input.</p>
        <p>The first eligible capture seals each prediction, including a missing-input deferral. Later captures cannot upgrade that prediction. Pending candidate outcomes can fill in when their paired evidence arrives; recorded outcomes are preserved.</p>
        <dl className="experiment-facts"><div><dt>Experiment</dt><dd><code>{protocol.experiment_id}</code></dd></div>
          <div><dt>Protocol frozen</dt><dd>{stamp(protocol.frozen_at)}</dd></div>
          <div><dt>Signal sessions</dt><dd>{protocol.sessions[0].date} through {protocol.sessions.at(-1)!.date} · 30 sessions / 60 symbol opportunities</dd></div>
          <div><dt>Last evidence capture</dt><dd>{view.latest_captured_at ? stamp(view.latest_captured_at) : "None recorded"}</dd></div>
          <div><dt>Reader checked</dt><dd>{stamp(feed.checked_at)} · this does not make market evidence current</dd></div></dl>
        <details><summary>Fixed benchmarks and evaluation criteria</summary><ul>
          <li>Cash benchmark: zero return, with no interest assumed.</li>
          <li>Wait until 15 minutes after the extended session closes for completed inputs. Record the prediction at least five minutes before the next declared extended-session open.</li>
          <li>Control benchmark: equal-weight QQQ/SPY opening-price return over the same dates and unit gross exposure.</li>
          <li>Thirty signal sessions, with at least 12 observed candidates as an operational coverage minimum. This is not a statistical power calculation. Missing inputs, late predictions, abstentions, and pending outcomes remain visible.</li>
          <li>A positive descriptive result requires both mean candidate gross return and mean gross excess over the control to be strictly positive. This is not statistical significance or evidence of an economic edge.</li>
          <li>Fees, slippage, capacity, continuity, risk, and uncertainty remain unqualified. Net returns are unavailable. Parameters cannot change within this run. Review the result manually; the run does not automatically extend.</li>
        </ul><p>The IEX daily-bar open is an observational proxy; it is not verified as the regular-session opening auction. This differs from the original hypothesis’s execution basis.</p></details>
      </section>
      <section aria-labelledby="experiment-progress-heading"><h2 id="experiment-progress-heading">Recorded progress</h2>
        <dl className="experiment-counts"><div><dt>Predictions recorded</dt><dd>{summary.recorded_prediction_count} / {summary.opportunity_count}</dd></div>
          <div><dt>Awaiting prediction</dt><dd>{summary.pending_prediction_count}</dd></div><div><dt>Candidates</dt><dd>{summary.candidate_count}</dd></div>
          <div><dt>Abstentions</dt><dd>{summary.abstention_count}</dd></div><div><dt>Missed / missing input</dt><dd>{summary.missed_count} / {summary.missing_input_count}</dd></div>
          <div><dt>Observed / pending outcomes</dt><dd>{summary.observed_outcome_count} / {summary.pending_outcome_count}</dd></div></dl>
        <p className="experiment-conclusion"><strong>Current conclusion:</strong> {label(summary.conclusion)}</p>
      </section>
      <section aria-labelledby="experiment-comparison-heading"><h2 id="experiment-comparison-heading">Gross descriptive comparison</h2>
        <dl className="experiment-counts"><div><dt>Mean candidate gross return</dt><dd>{percent(summary.mean_gross_return)}</dd></div>
          <div><dt>Mean gross excess over control</dt><dd>{percent(summary.mean_gross_excess_over_control)}</dd></div>
          <div><dt>Positive gross outcome fraction</dt><dd>{percent(summary.positive_gross_outcome_fraction)}</dd></div></dl>
        <p>No net performance or realized trade P&amp;L is calculated. QQQ, SPY, and adjacent sessions are correlated; these are not independent samples. Displayed percentages round to three decimal places; the recorded decimal values are unchanged.</p>
      </section>
      <section aria-labelledby="experiment-observations-heading"><h2 id="experiment-observations-heading">Predictions and linked outcomes</h2>
        <p>All planned symbol opportunities remain listed. A saved prediction is preserved when its outcome arrives later. On narrow screens, scroll the table sideways to read outcomes and evidence.</p>
        <div className="experiment-table-scroll" role="region" aria-label="Experiment predictions and outcomes" tabIndex={0}><table><caption>Frozen schedule · recorded evidence only · return values are gross proxies</caption>
          <thead><tr><th scope="col">Signal session / symbol</th><th scope="col">Prediction</th><th scope="col">Previous-session return</th><th scope="col">Entry → exit</th><th scope="col">Linked outcome / benchmarks</th><th scope="col">Evidence reasons</th></tr></thead>
          <tbody>{protocol.sessions.flatMap((session) => protocol.universe.map((symbol) => {
            const row = predictions.get(`${session.date}:${symbol}`), outcome = row && outcomes.get(row.prediction_id);
            return <tr key={`${session.date}:${symbol}`}><th scope="row">{session.date}<span>{symbol}</span></th>
              <td>{row ? <><strong>{label(row.status)}</strong><small>Recorded {stamp(row.recorded_at)}</small></> : "Awaiting prediction"}</td>
              <td>{percent(row?.signal_return ?? null)}</td><td>{row ? <>{row.entry_session}<span>→ {row.exit_session}</span></> : "Not recorded"}</td>
              <td><OutcomeCell outcome={outcome} prediction={row} /></td><td>{row ? <details><summary>Reasons &amp; identity</summary>
                <ul>{[...row.reason_codes, ...(outcome?.reason_codes ?? [])].map((reason, index) => <li key={index}><code>{reason}</code></li>)}</ul>
                <code>{row.prediction_id}</code>{outcome ? <code>{outcome.outcome_id}</code> : null}</details> : "No record yet"}</td></tr>;
          }))}</tbody></table></div>
      </section>
      <details><summary>Journal integrity, provenance, and limitations</summary><dl className="experiment-facts"><div><dt>Verified local journal</dt><dd>{view.journal.event_count} events · {view.journal.evidence_blob_count} retained blobs</dd></div>
        <div><dt>Journal head</dt><dd><code>{view.journal.last_entry_sha256}</code></dd></div><div><dt>Method</dt><dd><code>{protocol.method_version}</code></dd></div>
        <div><dt>Original hypothesis</dt><dd><code>{protocol.original_hypothesis_id}</code></dd></div></dl>
        <p>Local clocks and retained receipts do not independently authenticate preregistration. Hashes demonstrate retained-byte consistency, not the truth or completeness of provider data.</p>
        <ul>{view.limitations.map((reason) => <li key={reason}><code>{reason}</code></li>)}</ul>
      </details>
    </> : null}
  </article>;
}

export function ShadowExperimentPage() {
  return <main className="shadow-experiment-page"><div className="experiment-page-inner"><nav aria-label="Research view navigation"><a href="/">Return to Captain’s Cabin</a><span>Read-only experiment</span></nav><ShadowExperiment /></div></main>;
}
