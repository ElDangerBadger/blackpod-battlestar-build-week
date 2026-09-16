import {
  Component,
  Suspense,
  lazy,
  useMemo,
  useState,
  type ComponentType,
  type ErrorInfo,
  type ReactNode,
} from "react";

import { NavigatorShipView } from "./NavigatorShipView";
import { NavigatorMarketProvenance } from "./NavigatorMarketProvenance";
import type { NavigatorOceanViewProps } from "./navigator-ocean/NavigatorOceanView";
import type { NavigatorMarketVariant } from "../contracts/navigatorCatalog";
import type { NavigatorCaptureSelection } from "../data/navigatorSelection";
import { useLiveNavigatorPrice } from "../data/useLiveNavigatorPrice";
import { liveNavigatorPriceUrl } from "../data/liveNavigatorPrice";
import "./navigator-captures.css";

type OceanModule = { default: ComponentType<NavigatorOceanViewProps> };
type OceanLoader = () => Promise<OceanModule>;

export type NavigatorOceanBoundaryProps = NavigatorOceanViewProps & Readonly<{
  capabilityProbe?: () => boolean;
  loadView?: OceanLoader;
  variants?: readonly NavigatorMarketVariant[];
  sourceIdentity?: string | null;
  fleetSymbols?: readonly string[];
  initialSymbol?: string | null;
  initialCapture?: NavigatorCaptureSelection | null;
  livePublicationId?: string | null;
}>;

const defaultLoader: OceanLoader = () => import("./navigator-ocean/NavigatorOceanView");

export function supportsWebGL(): boolean {
  if (typeof document === "undefined") return false;
  if (typeof navigator !== "undefined" && navigator.userAgent.toLowerCase().includes("jsdom")) return false;
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl2") || canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

class OceanErrorBoundary extends Component<{ children: ReactNode; fallback: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(_error: Error, _info: ErrorInfo) {
    // The user-facing fallback is intentionally sanitized; no mission data changes.
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

function OceanFallback({ props, reason }: { props: NavigatorOceanViewProps; reason: string }) {
  const latest = props.data.points.at(-1) ?? null;
  return (
    <section className="navigator-ocean-fallback" aria-label="Navigator canonical chart fallback">
      <p role="status"><strong>3D ocean unavailable; canonical chart shown.</strong> {reason}</p>
      <p>
        Latest captured bar: {latest ? new Date(latest.t * 1000).toISOString() : "Not present in mission artifact"} · {props.presentationMode} · {props.runMode}
        <br /><span>Captured at: {props.capturedAt ?? "Not recorded"}</span>
      </p>
      {props.data.summary.last_ma === null ? (
        <p>Final supplied MA{props.data.ma_period}: unavailable. No value was inferred or substituted.</p>
      ) : null}
      <NavigatorShipView data={props.data} variant="interactive" />
      <NavigatorMarketProvenance market={props.data} />
    </section>
  );
}

/** Eager, lightweight gate. The Three.js module is requested only after expansion and capability checks. */
export function NavigatorOceanBoundary({
  capabilityProbe = supportsWebGL,
  loadView = defaultLoader,
  variants = [],
  sourceIdentity = null,
  fleetSymbols = [],
  initialSymbol = null,
  initialCapture = null,
  livePublicationId = null,
  ...props
}: NavigatorOceanBoundaryProps) {
  const [runtimeUnavailable, setRuntimeUnavailable] = useState(false);
  const [priceMode, setPriceMode] = useState<"LIVE" | "CAPTURED">("LIVE");
  const [paused, setPaused] = useState(false);
  const key = (market: NavigatorOceanViewProps["data"]) => `${market.symbol}:${market.timeframe}:${market.ma_period}`;
  const [selectedKey, setSelectedKey] = useState<string | null>(() => {
    if (initialCapture) {
      // A precise Tape handoff must never silently select another pair or symbol.
      if (initialSymbol && initialSymbol !== initialCapture.symbol) return "invalid-initial-capture";
      const requested = `${initialCapture.symbol}:${initialCapture.timeframe}:${initialCapture.ma_period}`;
      return requested === key(props.data) ? null : requested;
    }
    if (!initialSymbol || initialSymbol === props.data.symbol) return null;
    const matches = variants.filter((item) => item.market.symbol === initialSymbol);
    const initial = matches.find((item) => item.market.timeframe === props.data.timeframe && item.market.ma_period === props.data.ma_period) ?? matches[0];
    return initial ? key(initial.market) : `${initialSymbol}:${props.data.timeframe}:${props.data.ma_period}`;
  });
  const variant = variants.find((item) => key(item.market) === selectedKey);
  const capturedProps = variant ? { ...props, data: variant.market, capturedAt: variant.capturedAt } : props;
  const selectedData = capturedProps.data;
  const liveAvailable = props.presentationMode === "LIVE" && props.runMode === "LIVE"
    && liveNavigatorPriceUrl(livePublicationId, selectedData.symbol) !== null;
  const live = useLiveNavigatorPrice({ publicationId: livePublicationId, symbol: selectedData.symbol,
    enabled: liveAvailable && priceMode === "LIVE" && !paused });
  const livePrice = liveAvailable && priceMode === "LIVE" && live.quote?.price !== null && live.quote?.trade_at
    ? { symbol: selectedData.symbol, price: live.quote.price, tradeAt: live.quote.trade_at, feed: live.quote.feed,
      status: paused || live.status === "PAUSED" ? "UNAVAILABLE" as const : live.status } : undefined;
  const selectedProps: NavigatorOceanViewProps = { ...capturedProps, livePrice };
  const allChoices = [props.data, ...variants.map((item) => item.market)];
  const choices = allChoices.filter((item) => item.symbol === selectedData.symbol);
  const symbols = [...new Set([props.data.symbol, ...fleetSymbols, ...allChoices.map((item) => item.symbol)])];
  const select = (market: NavigatorOceanViewProps["data"]) => setSelectedKey(
    key(market) === key(props.data) ? null : key(market),
  );
  const capability = useMemo(() => capabilityProbe(), [capabilityProbe]);
  const LazyOcean = useMemo(() => lazy(loadView), [loadView]);
  const fallbackReason = selectedData.points.length < 2
    ? "At least two supplied observations are required for the 3D history; the read-only SVG preserves the supplied point."
    : "The read-only SVG view preserves the same supplied observations.";
  const fallback = <OceanFallback props={selectedProps} reason={fallbackReason} />;
  const content = !capability || runtimeUnavailable || selectedData.points.length < 2 ? fallback : (
    <OceanErrorBoundary fallback={fallback}>
      <Suspense fallback={<p className="navigator-ocean-loading" role="status">Loading cinematic Navigator ocean…</p>}>
        <LazyOcean {...selectedProps} onRuntimeUnavailable={() => setRuntimeUnavailable(true)} />
      </Suspense>
    </OceanErrorBoundary>
  );

  if (!variants.length && !fleetSymbols.length && selectedKey === null && !liveAvailable) return content;

  return (
    <div className={`navigator-capture-view${liveAvailable ? " navigator-capture-view--with-live" : ""}`}>
      {liveAvailable ? <section className="navigator-live-price" aria-label="Live Navigator market data">
        <div className="navigator-live-price__controls">
          <strong>{selectedData.symbol} · {priceMode === "CAPTURED" ? "CAPTURED REFERENCE" : paused || live.status === "PAUSED" ? "UPDATES PAUSED" : live.status}</strong>
          <div role="group" aria-label="Navigator price source">
            <button type="button" aria-pressed={priceMode === "LIVE"} onClick={() => setPriceMode("LIVE")}>Live market data</button>
            <button type="button" aria-pressed={priceMode === "CAPTURED"} onClick={() => setPriceMode("CAPTURED")}>Captured reference</button>
          </div>
          {priceMode === "LIVE" ? <button type="button" onClick={() => setPaused((value) => !value)}>{paused ? "Resume live updates" : "Pause live updates"}</button> : null}
          {priceMode === "LIVE" && live.quote?.price !== null && live.quote?.price !== undefined ? <strong aria-label="Last received live trade">{new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(live.quote.price)}</strong> : null}
        </div>
        {priceMode === "LIVE" ? <>
          <p>Alpaca · {(live.event?.feed ?? live.quote?.feed) === "iex" ? "IEX: limited-exchange coverage, not the full U.S. market" : (live.event?.feed ?? live.quote?.feed) === "sip" ? "SIP: consolidated U.S. market feed" : "feed awaiting confirmation"}.</p>
          <p>Trade: {live.quote?.trade_at ?? "not received"} · received: {live.quote?.received_at ?? "not received"} · checked: {live.event?.checked_at ?? "not yet"}.</p>
          <p role="status">{paused || live.status === "PAUSED" ? "Live updates paused; any displayed trade is retained, not current."
            : live.status === "LIVE" ? "Receiving live trades. Ship price may move; captured history and MA remain fixed."
            : live.status === "STALE" ? "Last trade is outdated; awaiting a newer trade. Retained price is not current."
            : live.status === "UNAVAILABLE" ? "Live feed disconnected or unavailable. Any retained price is not current; reconnecting when available."
            : live.status === "WAITING" ? "Connected; waiting for a recent trade. Markets may be closed or this feed may have no recent trades. Any retained price is not current."
            : "Connecting to the read-only live market-data feed. Any retained price is not current."}</p>
        </> : <p>Showing saved market evidence only. Live subscription stopped; no live trade is applied to the ship.</p>}
        <p>Live prices are separate, transient market context—not mission evidence. Captured chart history, intervals, and moving averages are unchanged; the SVG fallback stays captured.</p>
      </section> : null}
      <section className="navigator-capture-controls" aria-label="Captured Navigator datasets">
        <label>Review symbol
          <select aria-label="Navigator review symbol" value={selectedData.symbol}
            onChange={(event) => {
              const available = allChoices.filter((item) => item.symbol === event.currentTarget.value);
              const next = available.find((item) => item.timeframe === selectedData.timeframe && item.ma_period === selectedData.ma_period)
                ?? available.find((item) => item.timeframe === selectedData.timeframe)
                ?? available.find((item) => item.timeframe === "1d" && item.ma_period === 250) ?? available[0];
              if (next) select(next);
            }}>
            {symbols.map((symbol) => <option key={symbol} value={symbol} disabled={!allChoices.some((item) => item.symbol === symbol)}>
              {symbol}{symbol === props.data.symbol ? " · original reference" : !allChoices.some((item) => item.symbol === symbol) ? " · not captured" : ""}
            </option>)}
          </select>
        </label>
        <label>Bar interval
          <select
            aria-label="Captured bar interval"
            value={selectedData.timeframe}
            onChange={(event) => {
              const available = choices.filter((item) => item.timeframe === event.currentTarget.value);
              const next = available.find((item) => item.ma_period === selectedData.ma_period) ?? available[0];
              if (next) select(next);
            }}
          >
            {([['1h', 'Hourly'], ['1d', 'Daily'], ['1wk', 'Weekly']] as const).map(([value, label]) => (
              <option key={value} value={value} disabled={!choices.some((item) => item.timeframe === value)}>{label}</option>
            ))}
          </select>
        </label>
        <label>Moving average
          <select
            aria-label="Captured moving average"
            value={selectedData.ma_period}
            onChange={(event) => {
              const next = choices.find((item) => item.timeframe === selectedData.timeframe && item.ma_period === Number(event.currentTarget.value));
              if (next) select(next);
            }}
          >
            {([20, 50, 100, 200, 250] as const).map((period) => (
              <option key={period} value={period} disabled={!choices.some((item) => item.timeframe === selectedData.timeframe && item.ma_period === period)}>MA{period} bars</option>
            ))}
          </select>
        </label>
        <button type="button" onClick={() => setSelectedKey(null)} disabled={selectedKey === null}>Original mission capture</button>
        <p role="status">
          {selectedKey !== null && !variant ? "Selected capture is no longer available; showing the original. " : ""}
          {selectedData.symbol} · {selectedData.timeframe} · MA{selectedData.ma_period} · captured {selectedProps.capturedAt ?? "time not recorded"}
          {" · "}{variant?.sourceIdentity ?? sourceIdentity ?? "mission capture"} · not streaming
        </p>
        {symbols.length > 1 ? <p>Chart selection only · recorded mission results and the Cabin overview stay unchanged. Only captured intervals and moving averages are available.</p> : null}
        {variant ? <details>
          <summary>Capture provenance</summary>
          <span>Navigator revision: {variant.navigatorGitRevision}</span>
          {variant.navigatorSourceSha256 ? <span>Backend source SHA-256: {variant.navigatorSourceSha256}{variant.navigatorWorktreeDirty ? " · includes uncommitted source changes" : ""}</span> : null}
          <span>Artifact: {variant.reference.path}</span>
          <span>SHA-256: {variant.reference.sha256}</span>
        </details> : null}
      </section>
      <div className="navigator-capture-view__renderer">{content}</div>
    </div>
  );
}
