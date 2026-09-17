import { useId, useMemo, useState } from "react";
import type { SentrySnapshot } from "../contracts/sentry";
import { changeLocalWatchlist } from "../data/localWatchlist";
import { hasNavigatorCapture } from "../data/navigatorSelection";
import { useSentryFeed } from "../data/useSentryFeed";
import type { MissionViewModel } from "../data/viewModel";
import "./sentry-ledger.css";

type Props = { enabled: boolean; mission: MissionViewModel; onOpenNavigator: (symbol: string) => void };
type Score = SentrySnapshot["powder_keg"] | NonNullable<SentrySnapshot["continuation"]>;

const CLASSIFICATIONS: Record<string, { label: string; explanation: string }> = {
  INELIGIBLE: { label: "Ineligible", explanation: "This observation did not meet the recorded eligibility rules. It is retained here so exclusions remain visible." },
  DORMANT: { label: "Dormant", explanation: "Sentry recorded no higher-priority classification for this observation. This does not establish safety or predict what happens next." },
  POWDER_KEG: { label: "Powder keg", explanation: "The recorded structural score met Sentry’s powder-keg rule. This describes supplied conditions, not a prediction of a price move." },
  WATCH: { label: "Watch", explanation: "The recorded ignition score reached Sentry’s watch category. This is a review label, not an instruction to trade." },
  CATALYST_DETECTED: { label: "Catalyst detected", explanation: "Sentry recorded a supplied material catalyst alongside its score criteria. The label does not prove that the event caused a price move." },
  IGNITION: { label: "Ignition", explanation: "The recorded ignition score reached Sentry’s ignition category. It describes this observation, not assured continuation." },
  BREAKOUT_DEVELOPING: { label: "Breakout developing", explanation: "The recorded ignition score reached Sentry’s breakout category. It is not a forecast or a confirmed future outcome." },
  CONFIRMED_MOMENTUM: { label: "Confirmed momentum", explanation: "The recorded ignition and continuation scores met Sentry’s momentum rules at this observation. “Confirmed” is the classifier’s name, not a guarantee of future gains." },
  EXTENDED: { label: "Extended", explanation: "Sentry recorded its extended-move condition. This is a separate caution state, not another name for confirmed momentum." },
  DILUTION_RISK: { label: "Dilution risk", explanation: "Sentry recorded a dilution-risk condition with priority over ordinary score categories. The supplied risks and source record below describe the evidence." },
  FAILED_EVENT: { label: "Failed event", explanation: "Sentry recorded its failed-event condition at this observation. This is a historical rule-based state, not a statement about every later outcome." },
  HALTED: { label: "Halted", explanation: "An active trading halt was recorded at the observation time. This saved state does not establish whether trading is halted now." },
  INSUFFICIENT_DATA: { label: "Insufficient data", explanation: "Sentry could not establish its minimum market-data requirements for this observation. Missing measurements are not treated as zero." },
};

function classification(value: string) { return CLASSIFICATIONS[value]?.label ?? value; }
function numeric(value: number | null | undefined, suffix = "") {
  return value === null || value === undefined ? "Not recorded" : `${value.toLocaleString("en-US", { maximumFractionDigits: 4 })}${suffix}`;
}
function dateLabel(value: string | null) {
  if (!value) return "Not recorded";
  return new Date(value).toLocaleString("en-US", { timeZone: "UTC", month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }) + " UTC";
}
function compareText(a: string, b: string) { return a < b ? -1 : a > b ? 1 : 0; }
function observationTime(value: string) {
  const seconds = BigInt(Math.floor(Date.parse(value) / 1000));
  const fraction = value.match(/\.(\d+)/)?.[1] ?? "";
  return seconds * 1_000_000_000n + BigInt(fraction.padEnd(9, "0").slice(0, 9));
}
function compareObservations(a: SentrySnapshot, b: SentrySnapshot) {
  const first = observationTime(a.observed_at);
  const second = observationTime(b.observed_at);
  return first > second ? -1 : first < second ? 1 : compareText(a.event_id, b.event_id);
}
function sameTime(a: SentrySnapshot, b: SentrySnapshot) { return observationTime(a.observed_at) === observationTime(b.observed_at); }
function RecordedList({ items, empty }: { items: readonly string[]; empty: string }) {
  return items.length ? <ul>{items.map((item, index) => <li key={index}>{item}</li>)}</ul> : <p className="sentry-muted">{empty}</p>;
}
function ScoreCard({ label, score }: { label: string; score: Score | null }) {
  const value = score?.total_score ?? null;
  return <div className="sentry-score"><span>{label}</span><strong>{value === null ? "—" : numeric(value)}</strong><small>{value === null ? "Not recorded" : "out of 100"}</small>
    <div className="sentry-score-track" aria-hidden="true"><span style={{ width: `${value ?? 0}%` }} /></div>
  </div>;
}
function ScoreDetails({ label, score }: { label: string; score: Score | null }) {
  if (!score) return <p>{label}: no score record supplied.</p>;
  return <details className="sentry-disclosure"><summary>{label} · {score.contributions.length} recorded factors</summary>
    <RecordedList items={score.reasons} empty="No score-level explanation recorded." />
    {score.contributions.length ? <ol className="sentry-factors">{score.contributions.map((factor, index) => <li key={index}>
      <strong>{factor.factor.replaceAll("_", " ")}</strong><span className="sentry-factor-points">{factor.contribution > 0 ? "+" : ""}{numeric(factor.contribution)} points</span>
      <p>{factor.reason || "No factor explanation recorded."}</p>
      <small>Observed: {factor.observed_value === null ? "Not recorded" : String(factor.observed_value)} · Threshold: {factor.threshold === null ? "Not recorded" : String(factor.threshold)} · Weight: {numeric(factor.configured_weight)}</small>
    </li>)}</ol> : <p>No individual factor contributions recorded.</p>}
    <h5>Score warnings</h5><RecordedList items={score.warnings} empty="No score warnings listed; this is not an all-clear." />
    <h5>Missing score inputs</h5><RecordedList items={score.missing_data_fields} empty="No missing score inputs listed." />
  </details>;
}

/** Presentation of supplied canonical observations only; no browser scoring or scanning. */
export function SentryLedger({ enabled, mission, onOpenNavigator }: Props) {
  const state = useSentryFeed({ enabled });
  const [search, setSearch] = useState("");
  const [stateFilter, setStateFilter] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ symbol: string; message: string } | null>(null);
  const id = useId();
  const feed = state.feed;
  const source = feed?.source;
  const observations = feed?.observations;
  const groups = useMemo(() => {
    const symbols = new Map<string, SentrySnapshot[]>();
    for (const entry of observations ?? []) {
      const existing = symbols.get(entry.symbol);
      if (existing) existing.push(entry);
      else symbols.set(entry.symbol, [entry]);
    }
    return [...symbols].sort(([a], [b]) => compareText(a, b)).map(([symbol, entries]) => ({ symbol, entries: entries.sort(compareObservations) }));
  }, [observations]);
  const states = [...new Set((observations ?? []).map((entry) => entry.classification))].sort();
  const visible = groups.filter(({ symbol, entries }) => symbol.toLowerCase().includes(search.trim().toLowerCase()) && (!stateFilter || entries.some((entry) => entry.classification === stateFilter)));
  const selected = visible.flatMap(({ entries }) => entries).find((entry) => entry.event_id === selectedId && (!stateFilter || entry.classification === stateFilter))
    ?? visible[0]?.entries.find((entry) => !stateFilter || entry.classification === stateFilter);
  const history = groups.find(({ symbol }) => symbol === selected?.symbol)?.entries ?? [];
  const research = source?.kind === "RESEARCH";
  const available = enabled && state.status === "READY" && Boolean(source);
  const canUseSymbol = available && !research;
  const canOpenNavigator = Boolean(canUseSymbol && selected && hasNavigatorCapture(mission, selected.symbol));
  const choose = (entry: SentrySnapshot) => { setSelectedId(entry.event_id); setFeedback(null); };
  const add = () => {
    if (!selected || !canUseSymbol) return;
    let storage: Storage | null;
    try { storage = window.localStorage; } catch { storage = null; }
    const result = changeLocalWatchlist(storage, { type: "add", symbol: selected.symbol });
    setFeedback({ symbol: selected.symbol, message: result.message });
  };

  return <div className="sentry-ledger">
    <div className="sentry-source-band">
      <div>
        <h3>{source ? research ? "Synthetic research archive — not live detections" : "Recorded observations — not a live scanner" : "Observation source not connected"}</h3>
        {!source ? <p>Connect a canonical observation archive to inspect Sentry’s saved results. No scan is started by opening this ledger.</p> : null}
      </div>
      <button type="button" onClick={state.refresh} disabled={!enabled || state.refreshing}>Refresh records</button>
    </div>
    <p className="sentry-readonly">Separate from mission warnings and analysis. No orders, trading authority, or automatic watchlist changes.</p>
    {state.status !== "READY" ? <div className="sentry-status" role="status">
      <strong>{state.status === "LOADING" ? "Reading observation archive…" : state.status === "DISABLED" ? "Archive refresh is paused" : state.status === "NOT_CONFIGURED" ? "No observation source configured" : "Observation source unavailable"}</strong>
      <p>{state.message}</p>
      {source ? <p>Showing the last successfully read archive below. It has not been confirmed current; symbol actions are paused.</p> : <p>No readable observations are available here. This does not mean there are no candidates or risks.</p>}
    </div> : null}
    {source && feed ? <>
      <dl className="sentry-archive-stats">
        <div><dt>Symbols in archive</dt><dd>{groups.length}</dd></div>
        <div><dt>Distinct observations</dt><dd>{observations?.length ?? 0}</dd></div>
        <div><dt>Latest observation</dt><dd className="sentry-stat-date">{dateLabel(source.latest_observed_at)}</dd></div>
      </dl>
      <details className="sentry-disclosure sentry-provenance"><summary>Source &amp; archive integrity · {source.label}</summary>
        <dl className="sentry-facts"><div><dt>Source kind</dt><dd>{research ? "Synthetic research archive" : "Recorded archive"}</dd></div>
          <div><dt>File</dt><dd>{source.file_name}</dd></div><div><dt>Last successful source check</dt><dd>{dateLabel(feed.checked_at)}</dd></div>
          <div><dt>Archive records</dt><dd>{source.raw_count} total · {source.duplicate_count} exact duplicates collapsed · {observations?.length ?? 0} distinct observations</dd></div>
          <div><dt>Size</dt><dd>{source.byte_size.toLocaleString("en-US")} bytes</dd></div><div><dt>SHA-256</dt><dd><code>{source.sha256}</code></dd></div>
        </dl><p>Refreshing re-reads saved records; it does not acquire new market data. Observation time is not the time this page was checked. Exact duplicate records are collapsed, but distinct observations remain available in each symbol’s history.</p>
      </details>
      {groups.length ? <>
        <div className="sentry-filters">
          <label htmlFor={`${id}-search`}>Find a symbol<input id={`${id}-search`} type="search" placeholder="Search archive symbols" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
          <label htmlFor={`${id}-state`}>Recorded classification<select id={`${id}-state`} value={stateFilter} onChange={(event) => setStateFilter(event.target.value)}><option value="">All recorded classifications</option>{states.map((value) => <option key={value} value={value}>{classification(value)}</option>)}</select></label>
        </div>
        <p className="sentry-count" role="status">Showing {visible.length} of {groups.length} symbols · {observations?.length ?? 0} distinct observations · filters include historical classifications.</p>
        <div className="sentry-workspace">
          <nav className="sentry-candidates" aria-label="Sentry recorded symbols">
            {visible.map(({ symbol, entries }) => {
              const entry = entries.find((item) => !stateFilter || item.classification === stateFilter)!;
              const ties = entries.filter((item) => sameTime(item, entry)).length;
              return <button key={symbol} type="button" className="sentry-candidate" aria-pressed={selected?.symbol === symbol} onClick={() => choose(entry)} aria-label={`Review ${symbol} Sentry observations`}>
                <span className="sentry-candidate-heading"><strong>{symbol}</strong><span>{entries.length} {entries.length === 1 ? "record" : "records"}</span></span>
                <span className={`sentry-state sentry-state--${entry.classification.toLowerCase()}`}>{classification(entry.classification)}</span>
                <small>{dateLabel(entry.observed_at)}{ties > 1 ? ` · ${ties} same-time records` : ""}</small>
              </button>;
            })}
            {visible.length === 0 ? <p>No recorded symbols match these filters.</p> : null}
          </nav>
          {selected ? <article className="sentry-observation" aria-labelledby={`${id}-detail-title`}>
            <header className="sentry-observation-heading"><span className="sentry-kicker">{research ? "Synthetic research observation" : "Saved observation"}</span><h3 id={`${id}-detail-title`}>{selected.symbol} <span>{classification(selected.classification)}</span></h3><p>{dateLabel(selected.observed_at)}</p></header>
            <div className="sentry-scores"><ScoreCard label="Powder-Keg" score={selected.powder_keg} /><ScoreCard label="Ignition" score={selected.ignition} /><ScoreCard label="Continuation" score={selected.continuation} /></div>
            <p className="sentry-muted">Rule-based scores copied from the record—not probabilities, forecasts, or trading recommendations. Hard-state rules can take precedence over high scores.</p>
            <p className="sentry-interpretation">{CLASSIFICATIONS[selected.classification]?.explanation ?? "Read the supplied classification alongside its recorded reasons and limitations below."}</p>
            <label className="sentry-history" htmlFor={`${id}-history`}>Observation history · {history.length} distinct records
              <select id={`${id}-history`} value={selected.event_id} onChange={(event) => { setSelectedId(event.target.value); setStateFilter(""); setFeedback(null); }}>{history.map((entry) => <option key={entry.event_id} value={entry.event_id}>{dateLabel(entry.observed_at)} · {classification(entry.classification)} · {entry.event_id}</option>)}</select>
            </label>
            {history.some((entry, index) => index > 0 && sameTime(entry, history[index - 1])) ? <p className="sentry-tie-note">Some observations share a timestamp. They are separate records, not evidence of a later state. Equal-time records use ascending event ID for a stable display order; no classification wins the tie.</p> : null}
            <section className="sentry-reasons" aria-label="Recorded explanation"><h4>Why this was recorded</h4><RecordedList items={selected.reasons} empty="No observation-level explanation was recorded. Review the supplied score factors below; no explanation is invented here." /></section>
            <section aria-label="Recorded market measurements"><h4>Price &amp; market activity at observation</h4>
              <dl className="sentry-facts"><div><dt>Recorded profile price</dt><dd>{numeric(selected.symbol_profile?.price)}</dd></div><div><dt>1-minute price change</dt><dd>{numeric(selected.features.price_change_1m_pct, "%")}</dd></div><div><dt>5-minute price change</dt><dd>{numeric(selected.features.price_change_5m_pct, "%")}</dd></div><div><dt>15-minute price change</dt><dd>{numeric(selected.features.price_change_15m_pct, "%")}</dd></div><div><dt>1-minute relative volume</dt><dd>{numeric(selected.features.volume_ratio_1m, "×")}</dd></div><div><dt>5-minute relative volume</dt><dd>{numeric(selected.features.volume_ratio_5m, "×")}</dd></div><div><dt>Cumulative relative volume</dt><dd>{numeric(selected.features.cumulative_relative_volume, "×")}</dd></div><div><dt>1-minute dollar volume</dt><dd>{numeric(selected.features.dollar_volume)}</dd></div><div><dt>Recorded spread</dt><dd>{numeric(selected.features.spread_pct, "%")}</dd></div></dl>
              <p className="sentry-muted">These are supplied measurements, not current quotes. Price and dollar-volume values retain source units; a currency is not inferred.</p>
            </section>
            <section className="sentry-cautions" aria-label="Recorded risks and missing information"><h4>Limits to keep in mind</h4><h5>Recorded risks</h5><RecordedList items={selected.risks} empty="No explicit risk flags listed in this record. That is not an all-clear." /><h5>Missing information</h5><RecordedList items={selected.missing_information} empty="No observation-level missing-information items listed. Individual factors may still have missing inputs below." /></section>
            <details className="sentry-disclosure"><summary>Eligibility &amp; measurement limitations</summary><p>Recorded eligibility: <strong>{selected.eligibility.eligible ? "Eligible under the supplied rules" : "Not eligible under the supplied rules"}</strong>. Eligibility is not approval or a recommendation.</p><RecordedList items={selected.eligibility.reasons} empty="No eligibility explanation recorded." /><h5>Eligibility warnings</h5><RecordedList items={selected.eligibility.warnings} empty="No eligibility warnings listed." /><h5>Missing eligibility fields</h5><RecordedList items={selected.eligibility.missing_fields} empty="No missing eligibility fields listed." /><h5>Measurement warnings</h5><RecordedList items={selected.features.warnings} empty="No measurement warnings listed." /><h5>Missing measurements</h5><RecordedList items={selected.features.missing_data_fields} empty="No missing measurement fields listed." /></details>
            <ScoreDetails label="Powder-Keg" score={selected.powder_keg} /><ScoreDetails label="Ignition" score={selected.ignition} /><ScoreDetails label="Continuation" score={selected.continuation} />
            <details className="sentry-disclosure"><summary>Original observation record · JSON</summary><p>Event ID: <code>{selected.event_id}</code>. Original supplied field names and values are preserved below, including catalyst, news, filing, and halt records.</p><pre>{JSON.stringify(selected, null, 2)}</pre></details>
            <div className="sentry-actions"><button type="button" disabled={!canUseSymbol} onClick={add}>Add {selected.symbol} to local watchlist</button><button type="button" disabled={!canOpenNavigator} onClick={() => { if (canOpenNavigator) onOpenNavigator(selected.symbol); }}>Review {selected.symbol} in Navigator</button></div>
            <p className="sentry-muted">{research ? "Symbol actions are disabled for synthetic research records: fictional labels must not be presented as verified securities." : !available ? "Symbol actions are paused until the observation source is available again." : "Adding a symbol saves an unverified label in this browser only; it does not change the fleet, fetch prices, or authorize trading."}{!research && available && !canOpenNavigator ? " No Navigator capture is attached for this symbol in the current mission." : ""}</p>
            <p className="sentry-feedback" role="status">{feedback?.symbol === selected.symbol ? feedback.message : ""}</p>
          </article> : null}
        </div>
        <p className="sentry-footer">Symbols are alphabetical. Each card shows its latest matching observation; equal timestamps are ordered by event ID. Classification filtering matches any observation, not only the latest. All distinct records remain in observation history. No scanner, provider request, or model run is activated by this view.</p>
      </> : <p className="sentry-status">This archive contains no observations. An empty archive does not establish that there are no candidates, hazards, or missing data.</p>}
    </> : null}
  </div>;
}
