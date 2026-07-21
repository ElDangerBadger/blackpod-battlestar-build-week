import { useMemo, useState } from "react";

import { HowToRead } from "./HowToRead";
import { NavigatorOceanScene } from "./NavigatorOceanScene";
import { projectNavigatorOcean } from "./projection";
import type { NavigatorOceanMarket } from "./types";
import "./navigator-ocean.css";

export type NavigatorOceanViewProps = Readonly<{
  data: NavigatorOceanMarket;
  presentationMode: "DEMO" | "LIVE";
  runMode: "REPLAY" | "LIVE";
  capturedAt: string | null;
  reducedMotion: boolean;
  onRuntimeUnavailable?: () => void;
}>;

function formatPrice(value: number | null, currency: string): string {
  if (value === null || !Number.isFinite(value)) return "Unavailable in supplied artifact";
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${value.toFixed(2)} ${currency}`;
  }
}

function formatTimestamp(value: number | string | null): string {
  if (typeof value === "number") return new Date(value * 1000).toISOString();
  if (value === null || value.trim() === "") return "Not present in mission artifact";
  return value;
}

/**
 * Lazy, prop-only 3D enhancement over canonical Navigator observations.
 * This module has no fetch/store/backend seam and creates no market facts.
 */
export function NavigatorOceanView({
  data,
  presentationMode,
  runMode,
  capturedAt,
  reducedMotion,
  onRuntimeUnavailable = () => undefined,
}: NavigatorOceanViewProps) {
  const [zoomT, setZoomT] = useState(reducedMotion ? 0.68 : 0.08);
  const projection = useMemo(() => projectNavigatorOcean(data), [data]);
  const first = data.points[0] ?? null;
  const latest = data.points.at(-1) ?? null;

  if (projection === null || latest === null) {
    return (
      <section className="navigator-ocean navigator-ocean--unavailable" role="status">
        <h3>3D ocean unavailable</h3>
        <p>No price observations are present in this mission artifact. No values were substituted.</p>
      </section>
    );
  }

  return (
    <section className="navigator-ocean" aria-label={`Expanded Navigator ocean for ${data.symbol}`} data-reduced-motion={reducedMotion}>
      <header className="navigator-ocean__identity">
        <div>
          <p className="navigator-ocean__kicker">Supplemental market context · not SHADOW plan output</p>
          <h3>{data.symbol} <span>{data.name}</span></h3>
        </div>
        <div className="navigator-ocean__badges" aria-label="Presentation and mission modes">
          <strong>{presentationMode}</strong>
          <span>{runMode}</span>
          <span>{data.timeframe}</span>
        </div>
      </header>

      <div className="navigator-ocean__scene-shell">
        <NavigatorOceanScene
          data={data}
          projection={projection}
          zoomT={zoomT}
          reducedMotion={reducedMotion}
          onZoomChange={setZoomT}
          onRuntimeUnavailable={onRuntimeUnavailable}
        />

        <dl className="navigator-ocean__facts" aria-label="Canonical Navigator market facts">
          <div><dt>Latest captured bar</dt><dd>{formatTimestamp(latest.t)}</dd></div>
          <div><dt>Captured at</dt><dd>{formatTimestamp(capturedAt)}</dd></div>
          <div><dt>Displayed close</dt><dd>{formatPrice(latest.c, data.currency)}</dd></div>
          <div><dt>Supplied MA{data.ma_period}</dt><dd>{formatPrice(projection.maNow, data.currency)}</dd></div>
          <div><dt>Price vs MA</dt><dd>{projection.maNow === null ? "Unavailable — not inferred" : data.summary.position}</dd></div>
          <div><dt>Sea state</dt><dd>{data.summary.volatility}</dd></div>
          <div><dt>History</dt><dd>{formatTimestamp(first?.t ?? null).slice(0, 10)} → {formatTimestamp(latest.t).slice(0, 10)}</dd></div>
          <div><dt>Observations</dt><dd>{data.points.length} supplied · {projection.sampled.length} rendered</dd></div>
        </dl>

        <div className="navigator-ocean__controls" aria-label="Presentation camera controls">
          <button type="button" onClick={() => setZoomT(0)} aria-pressed={zoomT === 0}>Ship view</button>
          <label>
            <span>Camera: perspective to chart</span>
            <input
              type="range"
              min="0"
              max="1"
              step="0.01"
              value={zoomT}
              aria-label="Camera vantage"
              onChange={(event) => setZoomT(Number(event.currentTarget.value))}
            />
          </label>
          <button type="button" onClick={() => setZoomT(1)} aria-pressed={zoomT === 1}>Chart view</button>
          <button type="button" onClick={() => setZoomT(reducedMotion ? 0.68 : 0.08)}>Reset camera</button>
        </div>

        <p className="navigator-ocean__interaction">
          Scroll to zoom · drag to pan · shift/right-drag to rotate · double-click to reset
        </p>
        <div className="navigator-ocean__ma-label" aria-hidden="true">MA{data.ma_period} bearing</div>
      </div>

      <HowToRead maPeriod={data.ma_period} />
      <p className="navigator-ocean__authority">
        Market series is a captured Navigator reference artifact. Operational Navigator state remains in the Navigator book.
      </p>
    </section>
  );
}

export default NavigatorOceanView;
