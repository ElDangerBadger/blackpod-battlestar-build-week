import { useState } from "react";
import { missionRelativeUrl } from "../data/loadMission";
import { createRecordedFleetOverview, ORACLE_COVERAGE_LABELS } from "../data/fleetOverview";
import {
  chooseNavigatorCapture, hasNavigatorCapture, navigatorCaptureKey, navigatorCaptures,
  type NavigatorCaptureChoice, type NavigatorCaptureSelection,
} from "../data/navigatorSelection";
import { isMissionRelativePath } from "../data/validate";
import type { MissionViewModel } from "../data/viewModel";
import { NavigatorMarketProvenance } from "./NavigatorMarketProvenance";

function price(value: number | null, currency: string): string {
  if (value === null) return "Not supplied";
  try { return new Intl.NumberFormat("en-US", { style: "currency", currency, minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value); }
  catch { return `${value.toFixed(2)} ${currency}`; }
}

function time(value: string | number | null): string {
  if (value === null) return "Not recorded";
  const date = new Date(typeof value === "number" ? value * 1000 : value);
  if (!Number.isFinite(date.getTime())) return "Not recorded";
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium", timeStyle: "medium", timeZone: "UTC",
  }).format(date) + " UTC";
}

function captureReference(capture: NavigatorCaptureChoice, originalSymbol: string | undefined) {
  const reference = capture.reference;
  if (!reference || reference.producer !== "navigator" || reference.schema_version !== "navigator.api.ohlc.v1"
    || !isMissionRelativePath(reference.path) || /[%\\]/.test(reference.path)) return null;
  const { symbol, timeframe, ma_period: period } = capture.market;
  if (capture.original) return reference.name === "navigator_market" && reference.path === "presentation/navigator_market.json" ? reference : null;
  const single = symbol === originalSymbol && reference.name === "navigator_market_variant"
    && reference.path === `presentation/navigator_variants/${timeframe}-ma${period}.json`;
  const fleet = reference.name === "navigator_fleet_market"
    && reference.path === `presentation/navigator_fleet/${symbol}-${timeframe}-ma${period}.json`;
  return single || fleet ? reference : null;
}

export function NavigatorReferenceTape({ mission, initialSymbol, onOpenNavigator }: {
  mission: MissionViewModel;
  initialSymbol?: string | null;
  onOpenNavigator: (symbol: string, selection: NavigatorCaptureSelection) => void;
}) {
  const original = mission.market.navigatorMarket;
  const captures = navigatorCaptures(mission);
  const fleet = createRecordedFleetOverview(mission);
  const symbols = [...new Set([...(original ? [original.symbol] : []), ...fleet.rows.map((row) => row.symbol), ...captures.map((capture) => capture.market.symbol)])];
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(() => initialSymbol ?? original?.symbol ?? symbols[0] ?? null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const choices = captures.filter((capture) => capture.market.symbol === selectedSymbol);
  const exact = selectedKey ? choices.find((capture) => navigatorCaptureKey(capture.market) === selectedKey) : undefined;
  const capture = exact ?? (selectedSymbol ? chooseNavigatorCapture(captures, selectedSymbol, original ?? undefined) : undefined);
  const market = capture?.market;
  const row = fleet.rows.find((item) => item.symbol === selectedSymbol);
  const latest = market?.points.at(-1);
  const interval = market ? { "1h": "Hourly", "1d": "Daily", "1wk": "Weekly" }[market.timeframe] : "";
  const position = market ? { above: "Above the moving average", below: "Below the moving average", near: "Near the moving average" }[market.summary.position] : "";
  const period = market ? `MA${market.ma_period}` : "";
  const evidence = capture ? captureReference(capture, original?.symbol) : null;
  const select = (next: NavigatorCaptureChoice) => setSelectedKey(navigatorCaptureKey(next.market));
  const numeric = (value: number | null) => value === null ? "Not recorded" : value.toLocaleString("en-US", { maximumFractionDigits: 4 });

  return <div className="navigator-reference-tape">
    {symbols.length || selectedSymbol ? <section className="reference-tape-selection" aria-label="Reference tape selection">
      <label>Review symbol
        <select aria-label="Reference tape symbol" value={selectedSymbol ?? ""} onChange={(event) => {
          const symbol = event.currentTarget.value;
          const next = chooseNavigatorCapture(captures, symbol, market ?? original ?? undefined);
          setSelectedSymbol(symbol);
          setSelectedKey(next ? navigatorCaptureKey(next.market) : null);
        }}>
          {selectedSymbol && !symbols.includes(selectedSymbol) ? <option value={selectedSymbol} disabled>{selectedSymbol} · no longer available</option> : null}
          {symbols.map((symbol) => <option key={symbol} value={symbol}>{symbol}{symbol === original?.symbol ? " · original reference" : !captures.some((item) => item.market.symbol === symbol) ? " · no chart capture" : ""}</option>)}
        </select>
      </label>
      {market ? <>
        <label>Bar interval
          <select aria-label="Reference tape bar interval" value={market.timeframe} onChange={(event) => {
            const available = choices.filter((choice) => choice.market.timeframe === event.currentTarget.value);
            const next = available.find((choice) => choice.market.ma_period === market.ma_period) ?? available[0];
            if (next) select(next);
          }}>
            {([["1h", "Hourly"], ["1d", "Daily"], ["1wk", "Weekly"]] as const).map(([value, label]) => <option key={value} value={value} disabled={!choices.some((item) => item.market.timeframe === value)}>{label}</option>)}
          </select>
        </label>
        <label>Moving average
          <select aria-label="Reference tape moving average" value={market.ma_period} onChange={(event) => {
            const next = choices.find((choice) => choice.market.timeframe === market.timeframe && choice.market.ma_period === Number(event.currentTarget.value));
            if (next) select(next);
          }}>
            {([20, 50, 100, 200, 250] as const).map((value) => <option key={value} value={value} disabled={!choices.some((item) => item.market.timeframe === market.timeframe && item.market.ma_period === value)}>MA{value} bars</option>)}
          </select>
        </label>
      </> : null}
      {original ? <button type="button" disabled={capture?.original === true} onClick={() => { setSelectedSymbol(original.symbol); setSelectedKey(null); }}>Original mission reference</button> : null}
      <p role="status">
        {selectedKey && !exact ? "The selected capture is no longer available. " : ""}
        {market && capture ? `${market.symbol} · ${market.timeframe} · MA${market.ma_period} · captured ${time(capture.capturedAt)} · not streaming`
          : selectedSymbol ? `No Navigator chart capture is available for ${selectedSymbol}; only recorded fleet details are shown when present.` : "No recorded symbol is available."}
      </p>
    </section> : null}
    <p className="notice-lede">{market ? `${market.symbol} · ${market.name}` : selectedSymbol ? `${selectedSymbol} · recorded item details` : "No captured market reference is attached to this mission."}</p>
    {market ? <p>{capture?.original ? "This is the mission's original captured price reference" : "This is the selected symbol's captured Navigator price reference"}—not a streaming quote, a holding, or a trade instruction. Selection changes this expanded detail view only; the mission record and original Cabin overview stay unchanged.</p> : <p>{selectedSymbol ? `No captured Navigator price or moving average is available for ${selectedSymbol}.` : "The mission record can still be read, but no price or moving average has been supplied for this tape."} No replacement values were created.</p>}
    {market && hasNavigatorCapture(mission, market.symbol) ? <button type="button" onClick={() => onOpenNavigator(market.symbol, { symbol: market.symbol, timeframe: market.timeframe, ma_period: market.ma_period })}>Open full Navigator</button> : null}
    {market && !hasNavigatorCapture(mission, market.symbol) ? <p>The selected capture can be read here. Full Navigator is unavailable while the mission's base chart capture is missing.</p> : null}
    {market && capture ? <>
    <section aria-label="Price snapshot">
      <h3>Price snapshot</h3>
      <dl className="reference-tape-facts">
        <div><dt>Latest captured close</dt><dd>{latest ? price(latest.c, market.currency) : "Not supplied"}</dd></div>
        <div><dt>Supplied {period}</dt><dd>{price(market.summary.last_ma, market.currency)}</dd></div>
        <div><dt>Price relative to {period}</dt><dd>{market.summary.last_ma === null ? "Unavailable—no moving average was supplied" : position}</dd></div>
        <div><dt>Recorded distance from {period}</dt><dd>{market.summary.last_ma === null ? "Not supplied" : `${market.summary.pct_vs_ma > 0 ? "+" : ""}${market.summary.pct_vs_ma.toFixed(2)}%`}</dd></div>
        <div><dt>Bar interval</dt><dd>{interval} · one observation per supplied bar</dd></div>
        <div><dt>Recorded sea state</dt><dd>{market.summary.volatility}</dd></div>
      </dl>
      {market.summary.last_ma === null
        ? <p>{period} refers to a {market.ma_period}-bar moving average, but no final value was supplied in this capture. The latest close is available; a current comparison with the average is not. No missing average was calculated here.</p>
        : <p>{period} is the supplied moving average over {market.ma_period} {interval.toLowerCase()} bars. The ship shows the captured close; the yellow bearing shows this average. Their separation describes the saved data, not what the price will do next.</p>}
      <p>“Sea state” is Navigator's recorded volatility category. It is visual market context, not a safety rating or permission to trade.</p>
    </section>
    <section aria-label="Capture timing">
      <h3>When this information was recorded</h3>
      <dl className="reference-tape-facts">
        <div><dt>Latest bar timestamp</dt><dd>{time(latest?.t ?? null)}</dd></div>
        <div><dt>Capture time</dt><dd>{time(capture.capturedAt)}</dd></div>
        <div><dt>History begins</dt><dd>{time(market.points[0]?.t ?? null)}</dd></div>
        <div><dt>Supplied observations</dt><dd>{market.points.length}</dd></div>
      </dl>
      <p>A bar's timestamp identifies its interval. Capture time says when the response was saved. Opening this module does not refresh either timestamp.</p>
    </section>
    <section aria-label="Market reference limits">
      <h3>How to use this reference</h3>
      <p>Use it to understand the chart's supplied prices and moving average. Oracle's fleet analysis and the Council/Governor decisions are separate records in their ledgers. This tape does not establish that a Navigator SHADOW plan exists.</p>
    </section>
    <details className="recorded-details"><summary>Source and exact recorded details</summary>
      <NavigatorMarketProvenance market={market} />
      <p>Capture source: {capture.sourceIdentity ?? "Not recorded"}</p>
      <p>Original timestamp: <code>{capture.capturedAt ?? "Not recorded"}</code></p>
      {capture.navigatorGitRevision ? <p>Navigator revision: <code>{capture.navigatorGitRevision}</code></p> : null}
      {capture.navigatorSourceSha256 ? <p>Backend source SHA-256: <code>{capture.navigatorSourceSha256}</code>{capture.navigatorWorktreeDirty ? " · includes uncommitted source changes" : ""}</p> : null}
      {evidence ? <p>Artifact SHA-256: <code>{evidence.sha256}</code></p> : null}
      <pre>{JSON.stringify({ timeframe: market.timeframe, summary: market.summary }, null, 2)}</pre>
      {evidence ? <a href={missionRelativeUrl(mission.baseUrl, evidence.path)} target="_blank" rel="noreferrer">{capture.original ? "Open original Navigator market artifact" : "Open selected Navigator market artifact"}</a> : null}
    </details>
    </> : null}
    {selectedSymbol && (fleet.rows.length > 0 || row) ? <section aria-label="Recorded fleet item">
      <h3>Fleet snapshot and analysis coverage</h3>
      {row ? <>
        {fleet.source === "normalized"
          ? <p>This is the separate saved fleet observation for {row.symbol}.{market ? " Its price and time can differ from the Navigator capture above; its currency is not inferred from the chart." : " Its price is shown in source units; no currency or chart values are inferred."}</p>
          : <p>The normalized snapshot is unavailable. Only diagnostic and candidate records for {row.symbol} are shown; no observed fleet price, observation time, or complete fleet membership is established by these records.</p>}
        <dl className="reference-tape-facts">
          <div><dt>Recorded fleet</dt><dd>{fleet.fleetId ?? "Not recorded"}</dd></div>
          <div><dt>Fleet snapshot time</dt><dd>{time(fleet.observedAt)}</dd></div>
          <div><dt>Fleet observation time</dt><dd>{time(row.timestamp)}</dd></div>
          <div><dt>Fleet captured price · source units</dt><dd>{numeric(row.price)}</dd></div>
          <div><dt>Fleet recorded return</dt><dd>{row.returnPct === null ? "Not recorded" : `${numeric(row.returnPct)}%`}</dd></div>
          <div><dt>Oracle measurement coverage</dt><dd>{ORACLE_COVERAGE_LABELS[row.coverage]}</dd></div>
          <div><dt>Council candidate classification</dt><dd>{row.candidateState ?? "Not recorded"}</dd></div>
        </dl>
        {row.candidateReasons.length ? <><h4>Recorded candidate reasons</h4><ul>{row.candidateReasons.map((reason, index) => <li key={index}>{reason}</li>)}</ul></> : null}
        <p>These are recorded analysis classifications, not positions or buy/sell instructions. A Navigator capture does not remove an Oracle exclusion or create trading authority.</p>
      </> : <p>No fleet row for {selectedSymbol} is present in the available recorded evidence. Its Navigator reference is separate from fleet membership.</p>}
      {fleet.notes.length ? <ul>{fleet.notes.map((note) => <li key={note}>{note}</li>)}</ul> : null}
      {fleet.links.length ? <details className="recorded-details"><summary>Fleet source evidence</summary><ul>{fleet.links.map(({ label, reference }) => <li key={reference.name}><a href={missionRelativeUrl(mission.baseUrl, reference.path)} target="_blank" rel="noreferrer">{label}</a></li>)}</ul></details> : null}
    </section> : null}
  </div>;
}
