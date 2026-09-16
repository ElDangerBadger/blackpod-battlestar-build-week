import { Html, Line } from "@react-three/drei";
import type { ThreeEvent } from "@react-three/fiber";
import { useMemo, useState } from "react";
import { Vector3 } from "three";

import { chartStretchX } from "./projection";
import { WAKE_FOAM_ORDER } from "./renderOrder";
import type {
  NavigatorOceanTimeframe,
  ProjectedNavigatorOcean,
} from "./types";

export type ChartViewProps = Readonly<{
  projection: ProjectedNavigatorOcean;
  zoomT: number;
  viewT: number;
  maPeriod: number;
  timeframe: NavigatorOceanTimeframe;
}>;

const AXIS_COLOR = "#3a4a5e";
const AXIS_STRONG_COLOR = "#66788f";
const PRICE_LINE_COLOR = "#facc15";

const PRICE_INTEGER = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 0,
});
const PRICE_ONE_DECIMAL = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 1,
});
const PRICE_TWO_DECIMALS = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const PERCENT_TWO_DECIMALS = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  signDisplay: "always",
});
const UTC_MONTH = new Intl.DateTimeFormat("en-US", {
  month: "short",
  timeZone: "UTC",
});

/**
 * Flat-chart furniture rendered from the already validated projection. At full
 * chart zoom the backdrop is genuinely opaque and writes depth, preventing the
 * ocean from leaking through or interleaving with the analytical layer.
 */
export function ChartView({
  projection,
  zoomT,
  viewT,
  maPeriod,
  timeframe,
}: ChartViewProps) {
  const [hover, setHover] = useState<{ index: number; series: "price" | "ma" } | null>(null);
  const hoverIndex = hover?.index ?? null;
  const stretch = useMemo(
    () => Math.round(chartStretchX(viewT) * 4) / 4,
    [viewT],
  );
  const {
    sampled,
    priceNow,
    priceToWorld,
    stepZ,
    zSpan,
    maPoints,
    wakePoints,
  } = projection;
  const total = sampled.length;

  const priceRange = useMemo(() => {
    let low = priceNow;
    let high = priceNow;
    for (const point of sampled) {
      low = Math.min(low, point.c);
      high = Math.max(high, point.c);
      if (point.ma !== null) {
        low = Math.min(low, point.ma);
        high = Math.max(high, point.ma);
      }
    }

    const flatSeriesFloor = Math.max(Math.abs(priceNow) * 0.01, 0.01);
    if (high - low < flatSeriesFloor) {
      const midpoint = (high + low) / 2;
      low = midpoint - flatSeriesFloor / 2;
      high = midpoint + flatSeriesFloor / 2;
    }
    return { low, high };
  }, [sampled, priceNow]);

  const priceStep = useMemo(
    () => niceStep((priceRange.high - priceRange.low) / 7),
    [priceRange.high, priceRange.low],
  );
  const priceTicks = useMemo(() => {
    const result: { price: number; x: number }[] = [];
    const first = Math.floor(priceRange.low / priceStep) * priceStep;
    const last = Math.ceil(priceRange.high / priceStep) * priceStep;

    for (let price = first; price <= last + priceStep * 0.5; price += priceStep) {
      result.push({
        price,
        x: (price - priceNow) * priceToWorld * stretch,
      });
    }
    return result;
  }, [priceNow, priceRange.high, priceRange.low, priceStep, priceToWorld, stretch]);

  const halfWidth =
    Math.max(4, ...priceTicks.map((tick) => Math.abs(tick.x))) * 1.06;
  // A sparse history must not enlarge the plot beyond the fixed camera frame.
  const timePadding = Math.min(stepZ * 0.5, zSpan * 0.025);
  const nearZ = timePadding;
  const farZ = -(zSpan + timePadding);

  const timeTicks = useMemo(() => {
    const result: { z: number; label: string }[] = [];
    const tickCount = Math.min(6, Math.max(1, total - 1));
    for (let tick = 0; tick <= tickCount; tick += 1) {
      const index = Math.round((tick / tickCount) * (total - 1));
      const point = sampled[index];
      if (!point) continue;
      const ageIndex = total - 1 - index;
      result.push({
        z: -ageIndex * stepZ,
        label: formatDate(point.t, timeframe),
      });
    }
    return result;
  }, [sampled, stepZ, timeframe, total]);

  const maBegin = useMemo(() => {
    const first = maPoints.find((point) => point !== null);
    return first ? { x: first[0] * stretch, z: first[2] } : null;
  }, [maPoints, stretch]);

  const opacity = clamp01((zoomT - 0.55) / 0.27);
  if (opacity <= 0 || total < 2) return null;

  const panelIsOpaque = opacity >= 0.999;
  const hoveredPoint = hoverIndex === null ? null : sampled[hoverIndex] ?? null;
  const hoveredWake = hoverIndex === null ? null : wakePoints[hoverIndex] ?? null;
  const hoverX = hoveredWake ? hoveredWake[0] * stretch : 0;
  const hoverZ = hoveredWake?.[2] ?? 0;
  const hoverMa = hoveredPoint?.ma ?? null;
  const hoverPercent =
    hoveredPoint && hoverMa !== null && hoverMa !== 0
      ? ((hoveredPoint.c - hoverMa) / hoverMa) * 100
      : null;

  function handlePointerMove(event: ThreeEvent<PointerEvent>) {
    event.stopPropagation();
    if (event.buttons) {
      setHover(null);
      return;
    }
    const ageIndex = Math.round(-event.point.z / stepZ);
    const index = clampInteger(total - 1 - ageIndex, 0, total - 1);
    const priceX = wakePoints[index][0] * stretch;
    const ma = maPoints[index];
    const series = ma && Math.abs(event.point.x - ma[0] * stretch) < Math.abs(event.point.x - priceX)
      ? "ma" : "price";
    setHover({ index, series });
  }

  return (
    <group>
      <mesh
        position={[0, 0.12, (nearZ + farZ) / 2]}
        rotation={[-Math.PI / 2, 0, 0]}
        renderOrder={1}
      >
        <planeGeometry args={[halfWidth * 2, Math.abs(nearZ - farZ)]} />
        <meshBasicMaterial
          color="#0b1622"
          transparent={!panelIsOpaque}
          opacity={panelIsOpaque ? 1 : opacity}
          depthTest={!panelIsOpaque}
          depthWrite={panelIsOpaque}
          toneMapped={false}
          polygonOffset
          polygonOffsetFactor={1}
          polygonOffsetUnits={1}
        />
      </mesh>

      <Line
        points={[
          [-halfWidth, 0.14, nearZ],
          [halfWidth, 0.14, nearZ],
          [halfWidth, 0.14, farZ],
          [-halfWidth, 0.14, farZ],
          [-halfWidth, 0.14, nearZ],
        ]}
        color={AXIS_STRONG_COLOR}
        lineWidth={1.4}
        transparent
        opacity={0.5 * opacity}
        toneMapped={false}
        depthWrite={false}
      />

      {priceTicks.map((tick, index) => (
        <Line
          key={`price-grid-${index}`}
          points={[
            [tick.x, 0.15, nearZ],
            [tick.x, 0.15, farZ],
          ]}
          color={AXIS_COLOR}
          lineWidth={1}
          dashed
          dashSize={6}
          gapSize={6}
          transparent
          opacity={0.3 * opacity}
          toneMapped={false}
          depthWrite={false}
        />
      ))}
      <Line
        points={[
          [0, 0.16, nearZ],
          [0, 0.16, farZ],
        ]}
        color={PRICE_LINE_COLOR}
        lineWidth={1.6}
        transparent
        opacity={0.5 * opacity}
        toneMapped={false}
        depthWrite={false}
      />

      {timeTicks.map((tick, index) => (
        <Line
          key={`time-grid-${index}`}
          points={[
            [-halfWidth, 0.15, tick.z],
            [halfWidth, 0.15, tick.z],
          ]}
          color={AXIS_COLOR}
          lineWidth={1}
          dashed
          dashSize={6}
          gapSize={6}
          transparent
          opacity={0.28 * opacity}
          toneMapped={false}
          depthWrite={false}
        />
      ))}

      {priceTicks.map((tick, index) => (
        <group key={`price-label-${index}`}>
          <Html
            position={[tick.x, 0.5, nearZ]}
            center
            zIndexRange={[20, 0]}
            style={{ opacity, pointerEvents: "none" }}
          >
            <div className="bp-axis-label bp-axis-label--right" aria-hidden="true">{formatPrice(tick.price)}</div>
          </Html>
          <Html
            position={[tick.x, 0.5, farZ]}
            center
            zIndexRange={[20, 0]}
            style={{ opacity, pointerEvents: "none" }}
          >
            <div className="bp-axis-label bp-axis-label--left" aria-hidden="true">{formatPrice(tick.price)}</div>
          </Html>
        </group>
      ))}

      {timeTicks.map((tick, index) => (
        <Html
          key={`time-label-${index}`}
          position={[-halfWidth, 0.5, tick.z]}
          center
          zIndexRange={[20, 0]}
          style={{ opacity, pointerEvents: "none" }}
        >
          <div className="bp-time-label" aria-hidden="true">{tick.label}</div>
        </Html>
      ))}

      <Html
        position={[halfWidth * 1.14, 0.5, (nearZ + farZ) / 2]}
        center
        zIndexRange={[20, 0]}
        style={{ opacity, pointerEvents: "none" }}
      >
        <div className="bp-axis-title" aria-hidden="true">PRICE</div>
      </Html>
      <Html
        position={[-halfWidth * 1.16, 0.5, (nearZ + farZ) / 2]}
        center
        zIndexRange={[20, 0]}
        style={{ opacity, pointerEvents: "none" }}
      >
        <div className="bp-axis-title" aria-hidden="true">
          ◀ OLDER&nbsp;&nbsp;·&nbsp;&nbsp;TIME&nbsp;&nbsp;·&nbsp;&nbsp;RECENT ▶
        </div>
      </Html>

      <Html
        position={[0, 0.6, nearZ]}
        center
        zIndexRange={[20, 0]}
        style={{ opacity, pointerEvents: "none" }}
      >
        <div className="bp-price-now" aria-hidden="true">{formatPrice(priceNow)}</div>
      </Html>

      {maBegin ? (
        <Html
          position={[maBegin.x, 0.6, maBegin.z]}
          center
          zIndexRange={[20, 0]}
          style={{ opacity: opacity * 0.9, pointerEvents: "none" }}
        >
            <div className="bp-ma-begin" aria-hidden="true">MA({maPeriod}) starts in view →</div>
        </Html>
      ) : null}

      <mesh
        position={[0, 0.2, (nearZ + farZ) / 2]}
        rotation={[-Math.PI / 2, 0, 0]}
        onPointerMove={handlePointerMove}
        onPointerDown={() => setHover(null)}
        onPointerOut={() => setHover(null)}
      >
        <planeGeometry args={[halfWidth * 2, Math.abs(nearZ - farZ)]} />
        <meshBasicMaterial
          transparent
          opacity={0}
          depthWrite={false}
          colorWrite={false}
        />
      </mesh>

      {hoveredPoint && hoveredWake ? (
        <group>
          <Line
            points={[
              [-halfWidth, 0.3, hoverZ],
              [halfWidth, 0.3, hoverZ],
            ]}
            color="#e6eef7"
            lineWidth={1.2}
            transparent
            opacity={0.5 * opacity}
            toneMapped={false}
            depthWrite={false}
            depthTest={false}
            renderOrder={WAKE_FOAM_ORDER + 1}
          />
          <mesh
            position={[hoverX, 0.34, hoverZ]}
            rotation={[-Math.PI / 2, 0, 0]}
            renderOrder={WAKE_FOAM_ORDER + 2}
          >
            <circleGeometry args={[Math.max(stepZ * 0.9, 3), 24]} />
            <meshBasicMaterial
              color="#ffffff"
              transparent
              opacity={0.95}
              toneMapped={false}
              depthWrite={false}
              depthTest={false}
            />
          </mesh>
          {hoverMa !== null && hoverIndex !== null && maPoints[hoverIndex] ? (
            <mesh
              position={[
                maPoints[hoverIndex]![0] * stretch,
                0.34,
                hoverZ,
              ]}
              rotation={[-Math.PI / 2, 0, 0]}
              renderOrder={WAKE_FOAM_ORDER + 2}
            >
              <circleGeometry args={[Math.max(stepZ * 0.7, 2.4), 20]} />
              <meshBasicMaterial
                color={PRICE_LINE_COLOR}
                transparent
                opacity={0.95}
                toneMapped={false}
                depthWrite={false}
                depthTest={false}
              />
            </mesh>
          ) : null}
          <Html
            position={[
              hover?.series === "ma" && hoverIndex !== null && maPoints[hoverIndex]
                ? maPoints[hoverIndex]![0] * stretch : hoverX,
              0.8,
              hoverZ,
            ]}
            calculatePosition={(object, camera, size) => {
              // Screen-pixel gutters keep the readout inside the canvas even
              // at the first/last observation or after a camera pan.
              const point = new Vector3().setFromMatrixPosition(object.matrixWorld).project(camera);
              return [
                Math.max(12, Math.min((point.x * 0.5 + 0.5) * size.width + 14, size.width - 212)),
                Math.max(12, Math.min((-point.y * 0.5 + 0.5) * size.height - 160, size.height - 160)),
              ];
            }}
            zIndexRange={[30, 10]}
            style={{ pointerEvents: "none" }}
          >
            <div className="bp-hover-tip" data-series={hover?.series} aria-hidden="true">
              <div className="bp-hover-date">
                {formatDate(hoveredPoint.t, timeframe, true)}
              </div>
              <div className="bp-hover-caption">Nearest captured observation</div>
              <div className={`bp-hover-row${hover?.series === "price" ? " bp-hover-row--active" : ""}`}>
                <span>Price</span>
                <b>{PRICE_TWO_DECIMALS.format(hoveredPoint.c)}</b>
              </div>
              <div className={`bp-hover-row${hover?.series === "ma" ? " bp-hover-row--active" : ""}`}>
                <span>MA({maPeriod})</span>
                <b>{hoverMa === null ? "—" : PRICE_TWO_DECIMALS.format(hoverMa)}</b>
              </div>
              {hoverPercent !== null ? (
                <div className="bp-hover-row">
                  <span>vs MA</span>
                  <b
                    className={
                      hoverPercent > 0.25
                        ? "green"
                        : hoverPercent < -0.25
                          ? "red"
                          : "gray"
                    }
                  >
                    {PERCENT_TWO_DECIMALS.format(hoverPercent)}%
                  </b>
                </div>
              ) : null}
            </div>
          </Html>
        </group>
      ) : null}
    </group>
  );
}

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value));
}

function clampInteger(value: number, low: number, high: number): number {
  return Math.max(low, Math.min(high, value));
}

function niceStep(raw: number): number {
  if (!Number.isFinite(raw) || raw <= 0) return 1;
  const magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
  const normalized = raw / magnitude;
  const factor =
    normalized < 1.5 ? 1 : normalized < 3 ? 2 : normalized < 7 ? 5 : 10;
  return factor * magnitude;
}

function formatPrice(value: number): string {
  if (value >= 1_000) return PRICE_INTEGER.format(value);
  if (value >= 100) return PRICE_ONE_DECIMAL.format(value);
  return PRICE_TWO_DECIMALS.format(value);
}

function formatDate(
  timestampSeconds: number,
  timeframe: NavigatorOceanTimeframe,
  includeYear = false,
): string {
  const date = new Date(timestampSeconds * 1_000);
  if (Number.isNaN(date.getTime())) return "—";

  const month = UTC_MONTH.format(date);
  const day = date.getUTCDate();
  const year = date.getUTCFullYear();
  if (timeframe === "1h") {
    const hour = String(date.getUTCHours()).padStart(2, "0");
    return includeYear
      ? `${month} ${day}, ${year} ${hour}:00 UTC`
      : `${month} ${day} ${hour}:00 UTC`;
  }
  return includeYear
    ? `${month} ${day}, ${year}`
    : `${month} ${day} '${String(year).slice(2)}`;
}

export default ChartView;
