import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
} from "react";

import "../styles/navigator-ship.css";

export type NavigatorShipPoint = Readonly<{
  /** Unix seconds supplied by Navigator's existing OHLC contract. */
  t: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
  ma: number | null;
  atr: number | null;
}>;

export type NavigatorShipSummary = Readonly<{
  last_price: number;
  last_ma: number | null;
  pct_vs_ma: number | null;
  position: string;
  trend_slope_pct: number | null;
  volatility: string;
  atr: number | null;
  atr_pct: number | null;
  ma_period: number;
  bar_count: number;
}>;

export type NavigatorShipLevels = Readonly<{
  entry: number | null;
  stop: number | null;
  target: number | null;
  support: number | null;
  resistance: number | null;
}>;

export type NavigatorShipData = Readonly<{
  symbol: string;
  name: string;
  category: string;
  timeframe: string;
  ma_period: number;
  currency: string;
  points: readonly NavigatorShipPoint[];
  summary: NavigatorShipSummary;
  levels?: NavigatorShipLevels;
  regime?: string | null;
}>;

export type NavigatorShipViewProps = Readonly<{
  data: NavigatorShipData;
  variant: "overview" | "interactive";
  className?: string;
}>;

type LevelKey = keyof NavigatorShipLevels;

const LEVELS: readonly Readonly<{ key: LevelKey; label: string; className: string }>[] = [
  { key: "entry", label: "Entry", className: "entry" },
  { key: "stop", label: "Stop", className: "stop" },
  { key: "target", label: "Target", className: "target" },
  { key: "support", label: "Support", className: "support" },
  { key: "resistance", label: "Resistance", className: "resistance" },
];

const PLOT = { left: 56, top: 36, width: 888, height: 342 } as const;
const MIN_ZOOM = 1;
const MAX_ZOOM = 8;

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

function visiblePointCount(total: number, zoom: number): number {
  if (total <= 2) return total;
  return Math.max(2, Math.ceil(total / zoom));
}

function formatPrice(value: number | null, currency: string): string {
  if (value === null || !Number.isFinite(value)) return "Not present";
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

function formatPercent(value: number | null): string {
  return value === null || !Number.isFinite(value) ? "Not present" : `${value.toFixed(2)}%`;
}

function shortTimestamp(value: number | undefined): string {
  if (value === undefined || !Number.isFinite(value)) return "Not present";
  return new Date(value * 1000).toISOString().slice(0, 10);
}

function linePath(
  points: readonly NavigatorShipPoint[],
  value: (point: NavigatorShipPoint) => number | null,
  x: (index: number) => number,
  y: (value: number) => number,
): string {
  let drawing = false;
  return points.map((point, index) => {
    const current = value(point);
    if (current === null || !Number.isFinite(current)) {
      drawing = false;
      return "";
    }
    const command = drawing ? "L" : "M";
    drawing = true;
    return `${command}${x(index).toFixed(2)},${y(current).toFixed(2)}`;
  }).filter(Boolean).join(" ");
}

function shipPath(x: number, y: number): string {
  return [
    `M ${x} ${y - 14}`,
    `L ${x + 13} ${y + 8}`,
    `L ${x + 5} ${y + 6}`,
    `L ${x} ${y + 14}`,
    `L ${x - 5} ${y + 6}`,
    `L ${x - 13} ${y + 8}`,
    "Z",
  ].join(" ");
}

/**
 * A read-only viewport over already-computed Navigator market observations.
 * It maps supplied values to SVG geometry; it never derives indicators, levels,
 * mission outcomes, or trading instructions.
 */
export function NavigatorShipView({ data, variant, className = "" }: NavigatorShipViewProps) {
  const [zoom, setZoom] = useState(MIN_ZOOM);
  const [windowStart, setWindowStart] = useState(0);
  const svgRef = useRef<SVGSVGElement>(null);
  const dragRef = useRef<{ pointerId: number; clientX: number; start: number } | null>(null);
  const rawId = useId();
  const clipId = `navigator-ship-${rawId.replaceAll(":", "")}`;

  useEffect(() => {
    setZoom(MIN_ZOOM);
    setWindowStart(0);
  }, [data.points, variant]);

  const count = visiblePointCount(data.points.length, zoom);
  const maxStart = Math.max(0, data.points.length - count);
  const safeStart = clamp(windowStart, 0, maxStart);
  const visiblePoints = data.points.slice(safeStart, safeStart + count);

  const geometry = useMemo(() => {
    const observedValues = visiblePoints.flatMap((point) => [point.l, point.h, point.c]);
    const movingAverageValues = visiblePoints.flatMap((point) => point.ma === null ? [] : [point.ma]);
    const levelValues = LEVELS.flatMap(({ key }) => {
      const value = data.levels?.[key];
      return value === null || value === undefined ? [] : [value];
    });
    const values = [...observedValues, ...movingAverageValues, ...levelValues].filter(Number.isFinite);
    const rawMinimum = values.length ? Math.min(...values) : 0;
    const rawMaximum = values.length ? Math.max(...values) : 1;
    const span = rawMaximum - rawMinimum || Math.max(Math.abs(rawMaximum) * 0.04, 1);
    const minimum = rawMinimum - span * 0.08;
    const maximum = rawMaximum + span * 0.08;
    const x = (index: number) => PLOT.left + (visiblePoints.length <= 1 ? PLOT.width : index * PLOT.width / (visiblePoints.length - 1));
    const y = (value: number) => PLOT.top + (maximum - value) / (maximum - minimum) * PLOT.height;
    const closePath = linePath(visiblePoints, (point) => point.c, x, y);
    const maPath = linePath(visiblePoints, (point) => point.ma, x, y);

    return { minimum, maximum, x, y, closePath, maPath };
  }, [data.levels, visiblePoints]);

  const zoomTo = (requested: number) => {
    const nextZoom = clamp(requested, MIN_ZOOM, MAX_ZOOM);
    const previousCount = visiblePointCount(data.points.length, zoom);
    const previousEnd = safeStart + previousCount;
    const nextCount = visiblePointCount(data.points.length, nextZoom);
    const nextMaximumStart = Math.max(0, data.points.length - nextCount);
    setZoom(nextZoom);
    setWindowStart(clamp(previousEnd - nextCount, 0, nextMaximumStart));
  };

  const resetViewport = () => {
    setZoom(MIN_ZOOM);
    setWindowStart(0);
  };

  const handleWheel = (event: ReactWheelEvent<SVGSVGElement>) => {
    if (variant !== "interactive") return;
    event.preventDefault();
    zoomTo(event.deltaY < 0 ? zoom * 1.35 : zoom / 1.35);
  };

  const handlePointerDown = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (variant !== "interactive" || maxStart === 0) return;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    dragRef.current = { pointerId: event.pointerId, clientX: event.clientX, start: safeStart };
  };

  const handlePointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const width = svgRef.current?.getBoundingClientRect().width || 1000;
    const deltaBars = Math.round(-(event.clientX - drag.clientX) / width * count);
    setWindowStart(clamp(drag.start + deltaBars, 0, maxStart));
  };

  const handlePointerUp = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (dragRef.current?.pointerId !== event.pointerId) return;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    dragRef.current = null;
  };

  const lastGlobalIndex = data.points.length - 1;
  const lastVisibleIndex = lastGlobalIndex - safeStart;
  const currentPoint = lastVisibleIndex >= 0 && lastVisibleIndex < visiblePoints.length
    ? visiblePoints[lastVisibleIndex]
    : null;
  const currentX = currentPoint ? geometry.x(lastVisibleIndex) : null;
  const currentY = currentPoint ? geometry.y(currentPoint.c) : null;
  const missingLevels = LEVELS.filter(({ key }) => data.levels?.[key] === null || data.levels?.[key] === undefined);
  const rootClassName = ["navigator-ship", `navigator-ship--${variant}`, className].filter(Boolean).join(" ");

  return (
    <figure className={rootClassName} aria-label={`Navigator ship view for ${data.symbol}`}>
      <header className="navigator-ship__header">
        <div>
          <strong>{data.symbol}</strong>
          <span>{data.name}</span>
        </div>
        <p>
          <span>{data.category}</span>
          <span>{data.timeframe}</span>
          <span>{data.currency}</span>
          {data.regime ? <span>Regime: {data.regime}</span> : null}
        </p>
      </header>

      {variant === "interactive" ? (
        <div className="navigator-ship__controls" aria-label="Navigator chart controls">
          <button type="button" onClick={() => zoomTo(zoom * 1.5)} disabled={zoom >= MAX_ZOOM} aria-label="Zoom in">
            +
          </button>
          <button type="button" onClick={() => zoomTo(zoom / 1.5)} disabled={zoom <= MIN_ZOOM} aria-label="Zoom out">
            −
          </button>
          <button type="button" onClick={resetViewport} disabled={zoom === MIN_ZOOM && safeStart === 0} aria-label="Reset chart view">
            Reset
          </button>
          <label>
            <span>History position</span>
            <input
              aria-label="History position"
              type="range"
              min={0}
              max={maxStart}
              value={safeStart}
              disabled={maxStart === 0}
              onChange={(event) => setWindowStart(Number(event.currentTarget.value))}
            />
          </label>
          <output aria-live="polite">{visiblePoints.length} of {data.points.length} bars</output>
        </div>
      ) : null}

      <div className="navigator-ship__plot-wrap">
        <svg
          ref={svgRef}
          className="navigator-ship__plot"
          viewBox="0 0 1000 430"
          role="img"
          aria-label={`${data.symbol} price history with supplied ${data.ma_period}-day moving average`}
          onWheel={handleWheel}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
        >
          <defs>
            <clipPath id={clipId}>
              <rect x={PLOT.left} y={PLOT.top} width={PLOT.width} height={PLOT.height} rx="5" />
            </clipPath>
            <linearGradient id={`${clipId}-sea`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#315460" />
              <stop offset="0.5" stopColor="#1b3f4a" />
              <stop offset="1" stopColor="#102c38" />
            </linearGradient>
          </defs>
          <rect className="navigator-ship__sea" x={PLOT.left} y={PLOT.top} width={PLOT.width} height={PLOT.height} rx="5" fill={`url(#${clipId}-sea)`} />
          <g className="navigator-ship__grid" clipPath={`url(#${clipId})`} aria-hidden="true">
            {[0, 1, 2, 3, 4].map((index) => (
              <line key={`h-${index}`} x1={PLOT.left} x2={PLOT.left + PLOT.width} y1={PLOT.top + index * PLOT.height / 4} y2={PLOT.top + index * PLOT.height / 4} />
            ))}
            {[0, 1, 2, 3, 4].map((index) => (
              <line key={`v-${index}`} y1={PLOT.top} y2={PLOT.top + PLOT.height} x1={PLOT.left + index * PLOT.width / 4} x2={PLOT.left + index * PLOT.width / 4} />
            ))}
          </g>

          <g clipPath={`url(#${clipId})`}>
            {LEVELS.map(({ key, label, className: levelClass }) => {
              const value = data.levels?.[key];
              if (value === null || value === undefined) return null;
              const y = geometry.y(value);
              return (
                <g className={`navigator-ship__level navigator-ship__level--${levelClass}`} key={key} data-testid={`level-${key}`}>
                  <line x1={PLOT.left} x2={PLOT.left + PLOT.width} y1={y} y2={y} />
                  <text x={PLOT.left + 8} y={y - 5}>{label} {formatPrice(value, data.currency)}</text>
                </g>
              );
            })}
            {geometry.maPath ? <path className="navigator-ship__ma" d={geometry.maPath} data-testid="moving-average-path" /> : null}
            {geometry.closePath ? <path className="navigator-ship__wake-shadow" d={geometry.closePath} aria-hidden="true" /> : null}
            {geometry.closePath ? <path className="navigator-ship__wake" d={geometry.closePath} data-testid="close-history-path" /> : null}
            {currentPoint && currentX !== null && currentY !== null ? (
              <g className="navigator-ship__vessel" data-testid="current-price-ship" aria-label={`Ship at latest close ${formatPrice(currentPoint.c, data.currency)}`}>
                <circle cx={currentX} cy={currentY} r="20" />
                <path d={shipPath(currentX, currentY)} />
              </g>
            ) : null}
          </g>

          <g className="navigator-ship__axis" aria-hidden="true">
            <text x={PLOT.left} y={PLOT.top - 9}>{formatPrice(geometry.maximum, data.currency)}</text>
            <text x={PLOT.left} y={PLOT.top + PLOT.height + 22}>{shortTimestamp(visiblePoints[0]?.t)}</text>
            <text x={PLOT.left + PLOT.width} y={PLOT.top + PLOT.height + 22} textAnchor="end">{shortTimestamp(visiblePoints.at(-1)?.t)}</text>
          </g>
          {!visiblePoints.length ? (
            <text className="navigator-ship__empty" x="500" y="220" textAnchor="middle">No price observations present in mission artifact</text>
          ) : null}
        </svg>
      </div>

      <figcaption className="navigator-ship__caption">
        <dl className="navigator-ship__summary">
          <div><dt>Last</dt><dd>{formatPrice(data.summary.last_price, data.currency)}</dd></div>
          <div><dt>MA{data.summary.ma_period}</dt><dd>{formatPrice(data.summary.last_ma, data.currency)}</dd></div>
          <div><dt>vs MA</dt><dd>{formatPercent(data.summary.pct_vs_ma)}</dd></div>
          <div><dt>Position</dt><dd>{data.summary.position}</dd></div>
          <div><dt>Trend slope</dt><dd>{formatPercent(data.summary.trend_slope_pct)}</dd></div>
          <div><dt>Sea state</dt><dd>{data.summary.volatility}</dd></div>
          <div><dt>ATR</dt><dd>{formatPrice(data.summary.atr, data.currency)} · {formatPercent(data.summary.atr_pct)}</dd></div>
          <div><dt>Bars</dt><dd>{data.summary.bar_count}</dd></div>
        </dl>
        <div className="navigator-ship__legend" aria-label="Chart legend and supplied navigation levels">
          <span className="navigator-ship__legend-item navigator-ship__legend-item--wake">Price wake</span>
          <span className="navigator-ship__legend-item navigator-ship__legend-item--ma">Supplied MA{data.ma_period}</span>
          {LEVELS.map(({ key, label, className: levelClass }) => {
            const value = data.levels?.[key];
            return value === null || value === undefined ? null : (
              <span key={key} className={`navigator-ship__legend-item navigator-ship__legend-item--${levelClass}`}>
                {label}: {formatPrice(value, data.currency)}
              </span>
            );
          })}
        </div>
        {missingLevels.length ? (
          <p className="navigator-ship__missing">
            <strong>Navigation levels not present:</strong>{" "}
            {missingLevels.map(({ label }) => label).join(", ")} — Not present in mission artifact.
          </p>
        ) : null}
      </figcaption>
    </figure>
  );
}
