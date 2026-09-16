import { useMemo, useState } from "react";

import { NavigatorMarketProvenance } from "../NavigatorMarketProvenance";
import { HowToRead } from "./HowToRead";
import { clampHistoryStart, historyStartIndex, sliceHistory, type HistoryPreset } from "./historyWindow";
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

function formatHistoryTimestamp(value: number | null, timeframe: NavigatorOceanMarket["timeframe"]): string {
  const timestamp = formatTimestamp(value);
  if (value === null) return timestamp;
  return timeframe === "1h"
    ? `${timestamp.slice(0, 10)} ${timestamp.slice(11, 16)} UTC`
    : timestamp.slice(0, 10);
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
  const [oceanExaggeration, setOceanExaggeration] = useState(1);
  const [history, setHistory] = useState<{ preset: HistoryPreset } | { timestamp: number }>({ preset: "all" });
  const customStart = "timestamp" in history
    ? data.points.findIndex((point) => point.t >= history.timestamp) : 0;
  const startIndex = "preset" in history
    ? historyStartIndex(data.points, history.preset)
    : clampHistoryStart(data.points, customStart < 0 ? data.points.length - 1 : customStart);
  const visibleData = useMemo(() => sliceHistory(data, startIndex), [data, startIndex]);
  const projection = useMemo(() => projectNavigatorOcean(visibleData), [visibleData]);
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

      <section className="navigator-ocean__history" aria-label="Navigator presentation settings">
        <div className="navigator-ocean__history-presets" role="group" aria-label="Visible history range">
          <strong>History</strong>
          {(["1M", "3M", "6M", "1Y", "all"] as const).map((preset) => (
            <button
              key={preset}
              type="button"
              aria-pressed={"preset" in history && history.preset === preset}
              onClick={() => setHistory({ preset })}
            >{preset === "all" ? "All history" : preset}</button>
          ))}
        </div>
        <label className="navigator-ocean__history-start">
          <span>From <output>{formatHistoryTimestamp(visibleData.points[0]?.t ?? null, data.timeframe)}</output></span>
          <input
            aria-label="History start"
            aria-valuetext={formatHistoryTimestamp(visibleData.points[0]?.t ?? null, data.timeframe)}
            type="range" min="0" max={Math.max(0, data.points.length - 2)} step="1"
            value={startIndex} disabled={data.points.length < 3}
            onChange={(event) => {
              const index = clampHistoryStart(data.points, Number(event.currentTarget.value));
              setHistory({ timestamp: data.points[index].t });
            }}
          />
          <span>to {formatHistoryTimestamp(latest.t, data.timeframe)}</span>
        </label>
        <label className="navigator-ocean__exaggeration">
          <span>Ship price / MA scale <output>{oceanExaggeration.toFixed(2)}×</output></span>
          <input
            aria-label="Ship price / MA exaggeration"
            type="range" min="0.2" max="2.5" step="0.05" value={oceanExaggeration}
            onChange={(event) => setOceanExaggeration(Number(event.currentTarget.value))}
          />
        </label>
        <p>View only · latest captured close stays anchored · chart view uses normal scale.</p>
      </section>

      <div className="navigator-ocean__scene-shell">
        <NavigatorOceanScene
          data={visibleData}
          projection={projection}
          oceanExaggeration={oceanExaggeration}
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
          <div><dt>Source history</dt><dd>{formatHistoryTimestamp(first?.t ?? null, data.timeframe)} → {formatHistoryTimestamp(latest.t, data.timeframe)}</dd></div>
          <div><dt>Visible history</dt><dd>{formatHistoryTimestamp(visibleData.points[0]?.t ?? null, data.timeframe)} → {formatHistoryTimestamp(latest.t, data.timeframe)}</dd></div>
          <div><dt>Observations</dt><dd>{data.points.length} supplied · {visibleData.points.length} selected · {projection.sampled.length} rendered</dd></div>
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
          Hover chart for values · scroll to zoom · drag to pan · shift/right-drag to rotate · double-click to reset
        </p>
        <div className="navigator-ocean__ma-label" aria-hidden="true">MA{data.ma_period} bearing</div>
      </div>

      <HowToRead maPeriod={data.ma_period}>
        <NavigatorMarketProvenance market={data} />
      </HowToRead>
      <p className="navigator-ocean__authority">
        Market series is a captured Navigator reference artifact. Operational Navigator state remains in the Navigator book.
      </p>
    </section>
  );
}

export default NavigatorOceanView;
