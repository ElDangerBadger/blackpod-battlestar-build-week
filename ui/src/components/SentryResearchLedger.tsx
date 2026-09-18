import { useId } from "react";
import type { SentryResearchArm, SentryResearchPolicy } from "../contracts/sentryResearch";
import { useSentryResearchFeed } from "../data/useSentryResearchFeed";
import "./sentry-research.css";

const ARM_NAMES: Record<SentryResearchArm, string> = {
  BASELINE: "Unchanged baseline",
  ELIGIBLE_INCUMBENT_FIRST: "Eligible incumbents first",
  ELIGIBLE_INCUMBENT_FIRST_MAX_2_NEW: "Incumbents first · at most two new",
};
const ROLES = { CONTROL: "Control", PRIMARY: "Predeclared primary", EXPLORATORY: "Exploratory workload cap" };
const decimal = (value: number) => value.toLocaleString("en-US", { maximumFractionDigits: 4, minimumFractionDigits: 2 });
const percent = (value: number) => `${(value * 100).toLocaleString("en-US", { maximumFractionDigits: 2 })}%`;
const volumeLabel = (value: string) => BigInt(value).toLocaleString("en-US");
const dateLabel = (value: string) => new Date(value).toLocaleString("en-US", { timeZone: "UTC", month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }) + " UTC";
const dayLabel = (value: string) => new Date(`${value}T00:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric", year: "numeric" });

function Contributors({ policy }: { policy: SentryResearchPolicy }) {
  return <details className="research-disclosure">
    <summary>{ARM_NAMES[policy.arm]} · historical attention frequency</summary>
    <div className="research-contributors">
      {policy.windows.map((window) => <div key={window.lookback}>
        <h5>{window.lookback}-session baseline</h5>
        <p>{decimal(window.mean_selected)} mean names selected per session · {percent(window.eligible_coverage)} of eligible symbol-sessions covered.</p>
        <table><caption>Supplied top {window.top_symbols.length} historical contributors · {window.lookback}-session baseline</caption>
          <thead><tr><th scope="col">Symbol</th><th scope="col">Sessions selected</th></tr></thead>
          <tbody>{window.top_symbols.map((entry) => <tr key={entry.symbol}><th scope="row">{entry.symbol}</th><td>{entry.selected_sessions} / {window.sessions}</td></tr>)}</tbody>
        </table>
        {window.top_symbols.length === 0 ? <p>No contributor entries supplied.</p> : null}
      </div>)}
    </div>
  </details>;
}

/** A summary of supplied research artifacts, never a browser research engine. */
export function SentryResearchLedger({ enabled }: { enabled: boolean }) {
  const state = useSentryResearchFeed({ enabled });
  const id = useId();
  const feed = state.feed, source = feed?.source, study = feed?.study, prospective = feed?.prospective;
  return <div className="sentry-research">
    <header className="research-banner">
      <div><span className="research-kicker">General equity &amp; ETF · research only</span><h3>Historical research, not live detections</h3>
        <p>Recorded historical market-data research, separate from Microcap observations. No policy is promoted and no winner is selected.</p></div>
      <button type="button" onClick={state.refresh} disabled={!enabled || state.refreshing}>{state.refreshing ? "Reading checkpoint…" : "Refresh research records"}</button>
    </header>
    <p className="research-note">Read-only evidence. Opening or refreshing this tab does not start the collector, acquire market data, run a model, or change the fleet.</p>
    {state.status !== "READY" ? <div className="research-alert" role="status">
      <strong>{state.status === "LOADING" ? "Reading the research checkpoint…" : state.status === "NOT_CONFIGURED" ? "Research checkpoint not configured" : state.status === "DISABLED" ? "Research reading is paused" : "Research checkpoint unavailable"}</strong>
      <p>{state.message}</p>
      {source ? <p>The last verified archive remains visible below. It has not been refreshed; current availability is unconfirmed.</p> : <p>No research results have been verified here. Missing evidence is not an all-clear.</p>}
    </div> : null}
    {source && study && prospective && feed ? <>
      <dl className="research-timeband">
        <div><dt>Archive as of</dt><dd>{dateLabel(source.archive_as_of)}</dd></div>
        <div><dt>Last successful reader check</dt><dd>{dateLabel(feed.checked_at)}</dd></div>
      </dl>
      <p className="research-note">A newer reader check does not make the historical results or collector checkpoint newer. Scheduler and capture states below describe the archived checkpoint, not current service health.</p>
      <section aria-labelledby={`${id}-development`}>
        <div className="research-section-heading"><h3 id={`${id}-development`}>Development comparison · 2023–2024</h3><span className="research-badge">Research only</span></div>
        <p>References were fitted on <strong>2019–2022</strong>. The comparison covers {study.session_count} development sessions already seen by V1—not an independent holdout. The 20- and 60-session baselines are measurement windows, not selectable bar intervals.</p>
        <dl className="research-facts">
          <div><dt>Fixed cohort</dt><dd>{study.cohort.length} instruments</dd></div>
          <div><dt>Attention capacity</dt><dd>{study.criteria.capacity} names total · {study.criteria.per_profile_capacity} per profile</dd></div>
          <div><dt>New-name criterion</dt><dd>At most {study.criteria.mean_new_names_limit} new names per day, on average, in both windows</dd></div>
          <div><dt>Cross-window criterion</dt><dd>At least ⅔ mean set overlap (Jaccard)</dd></div>
        </dl>
        <div className="research-table-scroll" tabIndex={0} role="region" aria-label="Historical research policy comparison">
          <table className="research-comparison"><caption>Supplied workload results · both windows retained</caption>
            <thead><tr><th scope="col">Policy</th><th scope="col">20-session<br />new / day</th><th scope="col">60-session<br />new / day</th><th scope="col">Mean overlap</th><th scope="col">Recorded criteria</th></tr></thead>
            <tbody>{study.policies.map((policy) => <tr key={policy.arm}>
              <th scope="row">{ARM_NAMES[policy.arm]}<small>{ROLES[policy.role]}</small></th>
              {[20, 60].map((lookback) => <td key={lookback}>{decimal(policy.windows.find((window) => window.lookback === lookback)!.mean_new_names_per_day)}</td>)}
              <td>{percent(policy.mean_overlap)}</td>
              <td><span>New names: {policy.meets_churn ? policy.capped_by_construction ? "met by construction" : "met" : "not met"}</span><span>Overlap: {policy.meets_overlap ? "met" : "not met"}</span></td>
            </tr>)}</tbody>
          </table>
        </div>
        <p className="research-verdict">{study.all_policies_failed ? "No policy meets both workload criteria." : "Review the supplied criteria separately for each policy."} Workload criteria are not detection-accuracy, profitability, or trading thresholds.</p>
        <p>The two-new-name cap limits admissions by construction. Its lower churn is not independent proof of stability; it can leave eligible observations unselected. All three policies remain part of the research comparison.</p>
        <details className="research-disclosure"><summary>What these measures mean</summary>
          <p><strong>New names per day</strong> counts admissions to the attention list, including the initial empty-state admissions. <strong>Overlap</strong> compares the 20- and 60-session selected sets on the same day; two empty sets count as full overlap.</p>
          <p><strong>Eligible coverage</strong> is the supplied share of eligible symbol-sessions selected. It is not market coverage or a success rate. No false-positive or lifecycle accuracy conclusion is supplied here.</p>
        </details>
        <h4>Historical contributors—not today’s attention list</h4>
        <p className="research-note">These supplied top-six tables count selection frequency during 2023–2024. They are neither current signals nor investment rankings. A name absent from a top-six table does not imply zero selections. The browser does not score or rerank symbols.</p>
        {study.policies.map((policy) => <Contributors key={policy.arm} policy={policy} />)}
      </section>
      <section className="research-prospective" aria-labelledby={`${id}-prospective`}>
        <div className="research-section-heading"><h3 id={`${id}-prospective`}>Prospective experiment · archived checkpoint</h3><span className="research-badge research-badge--blocked">Blocked · {prospective.completed_sessions} / {prospective.planned_sessions} complete</span></div>
        <p>Fixed test window: {dayLabel(prospective.period.start)}–{dayLabel(prospective.period.end)}. The {dayLabel(prospective.warmup.session)} warmup is required before the first test session; it is not a prospective observation.</p>
        <div className="research-alert"><strong>Warmup failed · the full cohort was not sealed</strong>
          <p>{prospective.warmup.ready_symbols} symbol captures ready · {prospective.warmup.failed_symbols} failed · {prospective.warmup.blocked_symbols} blocked, out of {prospective.warmup.expected_symbols}. {prospective.warmup.provider_requests} provider requests were recorded.</p>
          <p>{prospective.warmup.failure_evidence_sealed ? "Failure evidence was sealed. That preserves the failure; it does not mean the warmup succeeded." : "No sealed failure-evidence checkpoint is supplied."}</p>
        </div>
        <h4>Why the warmup stopped</h4>
        <p><strong>{prospective.warmup.conflict.symbol}</strong> had a recorded {prospective.warmup.conflict.fields.join(", ")} conflict on {dayLabel(prospective.warmup.conflict.session)}. Prior volume: <strong>{volumeLabel(prospective.warmup.conflict.prior_volume)}</strong>; incoming volume: <strong>{volumeLabel(prospective.warmup.conflict.incoming_volume)}</strong>. Neither vintage has been established here as correct. The existing data was not silently replaced.</p>
        <p>Missing or failed evidence cannot be backfilled into prospective success, and the fixed test dates cannot roll forward. No completed 56-symbol warmup or prospective result is implied by the successful partial captures.</p>
        <details className="research-disclosure"><summary>Capture timing &amp; unresolved calendar evidence</summary>
          <dl className="research-facts"><div><dt>First recorded capture</dt><dd>{dateLabel(prospective.warmup.first_captured_at)}</dd></div><div><dt>Last recorded capture</dt><dd>{dateLabel(prospective.warmup.last_captured_at)}</dd></div>
            <div><dt>Recorded experiment status</dt><dd><code>{prospective.status}</code></dd></div><div><dt>Scheduler at archived checkpoint</dt><dd>{prospective.scheduler_loaded_at_archive ? "Recorded as loaded then; current state not checked" : "Not recorded as loaded then; current state not checked"}</dd></div></dl>
          <p>{prospective.calendar_blocker_dates.length ? `Official Cboe early-close timing remains unresolved for: ${prospective.calendar_blocker_dates.map(dayLabel).join("; ")}.` : "No unresolved calendar dates listed in this checkpoint."} No missing clock is assumed or supplied by the browser.</p>
        </details>
      </section>
      <details className="research-disclosure"><summary>Full fixed cohort · {study.cohort.length} instruments</summary>
        <p>General equity: RESEARCH_ONLY. ETF: RESEARCH_ONLY. This is the supplied fixed research cohort, not the mission fleet or a live watchlist. No symbols can be added, removed, or sent to Navigator here.</p>
        <ul className="research-cohort" aria-label="Full research cohort">{study.cohort.map((symbol) => <li key={symbol}>{symbol}</li>)}</ul>
      </details>
      <details className="research-disclosure"><summary>Source integrity &amp; limitations · {source.label}</summary>
        <p>These are fixed checkpoint summaries. The reader checks the supplied summary files; their declared upstream cache and results hashes are not a fresh re-verification of the large upstream artifacts.</p>
        <dl className="research-facts"><div><dt>Development record</dt><dd><code>{study.development_id}</code></dd></div><div><dt>Frozen protocol</dt><dd><code>{prospective.manifest_id}</code></dd></div>
          <div><dt>Declared upstream cache hash</dt><dd><code>{source.declared_upstream_hashes.cache}</code></dd></div><div><dt>Declared upstream results hash</dt><dd><code>{source.declared_upstream_hashes.results}</code></dd></div></dl>
        <ul className="research-source-files">{source.files.map((file) => <li key={file.file_name}><strong>{file.file_name}</strong> · {file.byte_size.toLocaleString("en-US")} bytes<code>{file.sha256}</code></li>)}</ul>
        <ul>{feed.limitations.map((limitation, index) => <li key={index}>{limitation}</li>)}</ul>
      </details>
      <p className="research-footer">Observation only · no published current attention list · no Oracle/Council integration, orders, or trading authority.</p>
    </> : null}
  </div>;
}
