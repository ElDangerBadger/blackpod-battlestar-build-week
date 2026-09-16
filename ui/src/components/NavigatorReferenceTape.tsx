import { missionRelativeUrl } from "../data/loadMission";
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

export function NavigatorReferenceTape({ mission, onOpenNavigator }: { mission: MissionViewModel; onOpenNavigator: () => void }) {
  const market = mission.market.navigatorMarket;
  if (!market) return <div className="navigator-reference-tape">
    <p className="notice-lede">No captured market reference is attached to this mission.</p>
    <p>The mission record can still be read, but no price or moving average has been supplied for this tape. No replacement values were created.</p>
  </div>;
  const latest = market.points.at(-1);
  const interval = { "1h": "Hourly", "1d": "Daily", "1wk": "Weekly" }[market.timeframe];
  const position = { above: "Above the moving average", below: "Below the moving average", near: "Near the moving average" }[market.summary.position];
  const period = `MA${market.ma_period}`;
  const indexedEvidence = mission.market.artifactReference;
  const evidence = indexedEvidence?.path === "presentation/navigator_market.json"
    && indexedEvidence.name === "navigator_market"
    && indexedEvidence.schema_version === "navigator.api.ohlc.v1" ? indexedEvidence : null;
  return <div className="navigator-reference-tape">
    <p className="notice-lede">{market.symbol} · {market.name}</p>
    <p>This is the mission's original captured price reference—not a streaming quote, a holding, or a trade instruction. Choosing a different chart capture does not rewrite this tape.</p>
    <button type="button" onClick={onOpenNavigator}>Open full Navigator</button>
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
        <div><dt>Capture time</dt><dd>{time(mission.market.capturedAt)}</dd></div>
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
      <p>Capture source: {mission.market.sourceIdentity ?? "Not recorded"}</p>
      <p>Original timestamp: <code>{mission.market.capturedAt ?? "Not recorded"}</code></p>
      <pre>{JSON.stringify({ timeframe: market.timeframe, summary: market.summary }, null, 2)}</pre>
      {evidence ? <a href={missionRelativeUrl(mission.baseUrl, evidence.path)} target="_blank" rel="noreferrer">Open original Navigator market artifact</a> : null}
    </details>
  </div>;
}
