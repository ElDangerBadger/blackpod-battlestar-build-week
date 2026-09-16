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
import "./navigator-captures.css";

type OceanModule = { default: ComponentType<NavigatorOceanViewProps> };
type OceanLoader = () => Promise<OceanModule>;

export type NavigatorOceanBoundaryProps = NavigatorOceanViewProps & Readonly<{
  capabilityProbe?: () => boolean;
  loadView?: OceanLoader;
  variants?: readonly NavigatorMarketVariant[];
  sourceIdentity?: string | null;
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
  ...props
}: NavigatorOceanBoundaryProps) {
  const [runtimeUnavailable, setRuntimeUnavailable] = useState(false);
  const [selectedPair, setSelectedPair] = useState<string | null>(null);
  const pair = (market: NavigatorOceanViewProps["data"]) => `${market.timeframe}:${market.ma_period}`;
  const variant = variants.find((item) => pair(item.market) === selectedPair);
  const selectedProps = variant ? { ...props, data: variant.market, capturedAt: variant.capturedAt } : props;
  const selectedData = selectedProps.data;
  const choices = [props.data, ...variants.map((item) => item.market)];
  const select = (market: NavigatorOceanViewProps["data"]) => setSelectedPair(
    pair(market) === pair(props.data) ? null : pair(market),
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

  if (!variants.length && selectedPair === null) return content;

  return (
    <div className="navigator-capture-view">
      <section className="navigator-capture-controls" aria-label="Captured Navigator datasets">
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
        <button type="button" onClick={() => setSelectedPair(null)} disabled={selectedPair === null}>Original mission capture</button>
        <p role="status">
          {selectedPair !== null && !variant ? "Selected capture is no longer available; showing the original. " : ""}
          {selectedData.timeframe} · MA{selectedData.ma_period} · captured {selectedProps.capturedAt ?? "time not recorded"}
          {" · "}{variant?.sourceIdentity ?? sourceIdentity ?? "mission capture"} · not streaming
        </p>
        {variant ? <details>
          <summary>Capture provenance</summary>
          <span>Navigator revision: {variant.navigatorGitRevision}</span>
          <span>Artifact: {variant.reference.path}</span>
          <span>SHA-256: {variant.reference.sha256}</span>
        </details> : null}
      </section>
      <div className="navigator-capture-view__renderer">{content}</div>
    </div>
  );
}
