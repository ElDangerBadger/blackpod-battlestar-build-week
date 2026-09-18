import { useId } from "react";
import type { SentryScanEntry, SentryScanFile, SentryScanSymbol } from "../contracts/sentryScan";
import { useSentryScanFeed } from "../data/useSentryScanFeed";
import "./sentry-research.css";
import "./sentry-scan.css";

const dateLabel = (value: string) => new Date(value).toLocaleString("en-US", { timeZone: "UTC", month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }) + " UTC";
const dayLabel = (value: string) => new Date(`${value}T00:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric", year: "numeric" });
const profileLabel = (value: string | null) => value === "GENERAL_EQUITY" ? "General equity" : value === "ETF" ? "ETF" : "Not established";
const percentileLabel = (value: number | null) => value === null ? "No eligible percentile" : `${(value * 100).toLocaleString("en-US", { maximumFractionDigits: 2 })}%`;
function Codes({ values, empty }: { values: string[]; empty: string }) {
  return values.length ? <ul className="scan-codes">{values.map((value, index) => <li key={index}><code>{value}</code></li>)}</ul> : <p>{empty}</p>;
}
function FileEvidence({ file }: { file: SentryScanFile }) {
  return <p className="scan-file"><strong>{file.file_name}</strong> · {file.byte_size.toLocaleString("en-US")} bytes<code>{file.sha256}</code></p>;
}
function EntryEvidence({ entry }: { entry: SentryScanEntry }) {
  return <details className="scan-entry-details"><summary>Recorded reasons &amp; evidence · {entry.symbol}</summary>
    <Codes values={entry.reasons} empty="No reason supplied." />
    <h5>Quality flags</h5><Codes values={entry.quality_flags} empty="No quality flags listed; this is not an all-clear." />
    <dl className="research-facts"><div><dt>Sensor record</dt><dd><code>{entry.sensor_result_id}</code></dd></div>
      <div><dt>Winning assessment</dt><dd><code>{entry.winning_assessment_id ?? "None recorded"}</code></dd></div>
      <div><dt>Calibration reference</dt><dd><code>{entry.calibration_id ?? "None recorded"}</code></dd></div></dl>
  </details>;
}
function InputEvidence({ row }: { row: SentryScanSymbol }) {
  return <details className="research-disclosure"><summary>{row.symbol} · {row.status === "OBSERVED" ? "Observation recorded" : "Excluded before selection"} · {profileLabel(row.profile)}</summary>
    <Codes values={row.reasons} empty="No input-level exclusion reason recorded." />
    {row.history ? <><h5>Declared history</h5><FileEvidence file={row.history} />
      <dl className="research-facts"><div><dt>Provider</dt><dd>{row.history.provider}</dd></div><div><dt>Captured at</dt><dd>{dateLabel(row.history.captured_at)}</dd></div>
        <div><dt>History range</dt><dd>{row.history.first_session ?? "Unavailable"} to {row.history.last_session ?? "Unavailable"} · {row.history.row_count.toLocaleString("en-US")} rows</dd></div>
        <div><dt>Source receipt</dt><dd><code>{row.history.source_receipt_id}</code></dd></div></dl></> : <p>No usable history file reference supplied.</p>}
    {row.failure_evidence ? <><h5>Failure evidence</h5><FileEvidence file={row.failure_evidence} /><p><code>{row.failure_evidence.status}</code> · <code>{row.failure_evidence.receipt_id}</code></p></> : null}
    {row.history_validation ? <><h5>Recorded history validation</h5><p>Structurally valid: {row.history_validation.structurally_valid ? "yes" : "no"} · Research usable: {row.history_validation.research_usable ? "yes" : "no"}</p>
      <Codes values={row.history_validation.errors} empty="No validation errors listed." /><Codes values={row.history_validation.warnings} empty="No validation warnings listed." /><code>{row.history_validation.report_id}</code></> : <p>No history-validation result supplied.</p>}
  </details>;
}

/** Read-only presentation of an operator-selected offline scan, not a live scanner. */
export function SentryScanLedger({ enabled }: { enabled: boolean }) {
  const state = useSentryScanFeed({ enabled });
  const id = useId();
  const feed = state.feed, source = feed?.source, scan = feed?.scan;
  return <div className="sentry-research sentry-scan">
    <header className="research-banner"><div><span className="research-kicker">General equity &amp; ETF · RESEARCH_ONLY</span>
      <h3>Recorded scan results—not live detections</h3><p>A separate offline snapshot. This is not the frozen V2 development comparison, a prospective success, or a published production attention list.</p></div>
      <button type="button" onClick={state.refresh} disabled={!enabled || state.refreshing}>{state.refreshing ? "Reading scan receipt…" : "Refresh scan records"}</button>
    </header>
    <p className="research-note">Opening or refreshing only reads a saved receipt. It does not run a scan, call a market-data provider, start a model, change the fleet, or submit orders.</p>
    {state.status !== "READY" ? <div className="research-alert" role="status"><strong>{state.status === "LOADING" ? "Reading recorded scan…" : state.status === "NOT_CONFIGURED" ? "No scan receipt configured" : state.status === "DISABLED" ? "Scan receipt reading is paused" : "Scan receipt unavailable"}</strong>
      <p>{state.message}</p>{source ? <p>The last successfully read receipt remains visible. It has not been refreshed; current availability is unconfirmed. These are not current market detections.</p> : <p>No scan results are available here. Missing evidence is not an all-clear, and no substitute scan is shown.</p>}</div> : null}
    {scan && source && feed ? <>
      <dl className="research-timeband"><div><dt>Observed session</dt><dd>{dayLabel(scan.session_date)}</dd></div><div><dt>Scan as of</dt><dd>{dateLabel(scan.as_of)}</dd></div>
        <div><dt>Last successful reader check</dt><dd>{dateLabel(feed.checked_at)}</dd></div><div><dt>Source kind</dt><dd>Recorded offline research snapshot</dd></div></dl>
      <p className="research-note">A recent reader check does not make this scan or its market data current. The scan remains tied to its recorded session and evidence.</p>
      <section aria-labelledby={`${id}-population`}><div className="research-section-heading"><h3 id={`${id}-population`}>Scan coverage</h3><span className="research-badge">Research only</span></div>
        <dl className="research-facts"><div><dt>Requested symbols</dt><dd>{scan.population.requested_count}</dd></div><div><dt>Observations recorded</dt><dd>{scan.population.observed_count}</dd></div><div><dt>Failed / excluded inputs</dt><dd>{scan.population.failed_count}</dd></div>
          <div><dt>Minimum history</dt><dd>{scan.configuration.minimum_history_sessions} sessions</dd></div><div><dt>Attention capacity per window</dt><dd>{scan.configuration.capacity} total · {scan.configuration.per_profile_capacity.GENERAL_EQUITY} general equity · {scan.configuration.per_profile_capacity.ETF} ETF</dd></div></dl>
        <p>Failed symbols remain visible below and do not replace valid observations. Passing input checks does not guarantee selection. Missing capacity is left empty; excluded symbols are not used to pad the list.</p>
      </section>
      <section aria-labelledby={`${id}-candidates`}><h3 id={`${id}-candidates`}>Recorded candidates · both windows retained</h3>
        <p>The 20- and 60-session baselines are measurement windows, not bar intervals. Candidate order and values are copied from the canonical receipt; the browser does not score or rerank them.</p>
        <p className="research-note">Percentile is a supplied reference comparison—not a probability of a price move, return forecast, or trading recommendation. Minimum supplied selection percentile: {percentileLabel(scan.configuration.minimum_percentile)}.</p>
        {scan.windows.map((window) => <article className="scan-window" key={window.lookback} aria-labelledby={`${id}-window-${window.lookback}`}>
          <div className="research-section-heading"><h4 id={`${id}-window-${window.lookback}`}>{window.lookback}-session baseline</h4><span className="research-badge">{window.selected.length} / {scan.configuration.capacity} selected</span></div>
          <p>{window.candidate_count} observed candidates · {window.eligible_candidate_count} eligible candidates · <strong>{window.capacity_remaining} unfilled slots · no padding</strong></p>
          {window.selected.length ? <div className="research-table-scroll" role="region" aria-label={`${window.lookback}-session selected candidates`} tabIndex={0}><table className="scan-candidates"><caption>Selected candidates · {window.lookback}-session baseline · supplied order</caption>
            <thead><tr><th scope="col">Symbol / profile</th><th scope="col">Percentile / metric</th><th scope="col">Recorded evidence</th></tr></thead>
            <tbody>{window.selected.map((entry) => <tr key={entry.symbol}><th scope="row">{entry.symbol}<small>{profileLabel(entry.profile)}</small></th><td>{percentileLabel(entry.percentile)}<code>{entry.metric_name ?? "No eligible metric"}</code></td><td><EntryEvidence entry={entry} /></td></tr>)}</tbody>
          </table></div> : <div className="research-alert"><strong>No candidates selected for this window.</strong><p>The empty result is retained. It is not a no-risk conclusion.</p></div>}
          <details className="research-disclosure"><summary>Observed but not selected · {window.excluded.length} · {window.lookback}-session baseline</summary>
            {window.excluded.length ? <ul className="scan-exclusions">{window.excluded.map((entry) => <li key={entry.symbol}><h5>{entry.symbol} · {profileLabel(entry.profile)} · {percentileLabel(entry.percentile)}</h5><Codes values={entry.reasons} empty="No exclusion reason supplied." /><EntryEvidence entry={entry} /></li>)}</ul> : <p>No observed candidates excluded from this window.</p>}
          </details><details className="research-disclosure"><summary>Selection provenance · {window.lookback}-session baseline</summary><dl className="research-facts"><div><dt>Selection ID</dt><dd><code>{window.selection_id}</code></dd></div><div><dt>Policy ID</dt><dd><code>{window.policy_id}</code></dd></div></dl></details>
        </article>)}
      </section>
      <section aria-labelledby={`${id}-failed`}><h3 id={`${id}-failed`}>Failed / excluded inputs · {scan.population.failed_count}</h3>
        <p>These symbols produced no observation for either window. Their supplied reasons and any failure evidence are preserved; they are not silently dropped or replaced.</p>
        {scan.symbols.filter((row) => row.status === "EXCLUDED").map((row) => <InputEvidence key={row.symbol} row={row} />)}
        {scan.population.failed_count === 0 ? <p>No input failures listed in this receipt. That does not establish current data health.</p> : null}
      </section>
      <details className="research-disclosure"><summary>Full requested population · {scan.population.requested_count} symbols</summary><ul className="research-cohort" aria-label="Scan requested population">{scan.population.requested.map((symbol) => <li key={symbol}>{symbol}</li>)}</ul><p>This recorded population is not the mission fleet or a watchlist editor. No symbol actions are available.</p></details>
      <details className="research-disclosure"><summary>Observed input provenance · {scan.population.observed_count} symbols</summary>{scan.symbols.filter((row) => row.status === "OBSERVED").map((row) => <InputEvidence key={row.symbol} row={row} />)}</details>
      <details className="research-disclosure"><summary>Receipt integrity &amp; limitations</summary>
        <p>This is an operator-selected local receipt. The reader validates its structure and self-hash consistency, not independent authenticity or the underlying history, metadata, and calibration files. Declared evidence has not been reverified by this reader.</p>
        <FileEvidence file={source} /><dl className="research-facts"><div><dt>Scan ID</dt><dd><code>{scan.scan_id}</code></dd></div><div><dt>Input manifest hash</dt><dd><code>{scan.manifest_sha256}</code></dd></div>
          <div><dt>Reference manifest</dt><dd><code>{scan.reference_manifest_id}</code></dd></div><div><dt>Validation protocol</dt><dd><code>{scan.validation_protocol_id}</code></dd></div></dl>
        <h5>Declared calibration references</h5><Codes values={scan.calibration_ids} empty="No references supplied." /><h5>Recorded limitations</h5><Codes values={scan.limitations} empty="No limitations listed; this does not establish safety." />
      </details><p className="research-footer">RESEARCH_ONLY · observation only · no published current attention universe · no Oracle/Council handoff, orders, or trading authority.</p>
    </> : null}
  </div>;
}
