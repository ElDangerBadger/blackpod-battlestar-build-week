import { Html, Line } from "@react-three/drei";
import { useMemo } from "react";

import { chartStretchX } from "./projection";
import { MA_GLOW_ORDER, MA_LINE_ORDER } from "./renderOrder";
import type {
  NavigatorOceanVector,
  ProjectedNavigatorOcean,
} from "./types";

export type MaBearingProps = Readonly<{
  projection: ProjectedNavigatorOcean;
  maPeriod: number;
  zoomT: number;
  viewT: number;
}>;

type MaLabel = Readonly<{
  position: [number, number, number];
  value: number;
}>;

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

function formatPrice(value: number): string {
  if (value >= 1_000) return PRICE_INTEGER.format(value);
  if (value >= 100) return PRICE_ONE_DECIMAL.format(value);
  return PRICE_TWO_DECIMALS.format(value);
}

function contiguousSegments(
  points: readonly (NavigatorOceanVector | null)[],
): [number, number, number][][] {
  const segments: [number, number, number][][] = [];
  let current: [number, number, number][] = [];

  for (const point of points) {
    if (point !== null) {
      current.push([point[0], point[1], point[2]]);
    } else {
      if (current.length > 1) segments.push(current);
      current = [];
    }
  }
  if (current.length > 1) segments.push(current);
  return segments;
}

/** Draws only supplied moving-average observations; null gaps remain gaps. */
export function MaBearing({
  projection,
  maPeriod,
  zoomT,
  viewT,
}: MaBearingProps) {
  const stretch = useMemo(
    () => Math.round(chartStretchX(viewT) * 4) / 4,
    [viewT],
  );
  const maPoints = useMemo(
    () =>
      projection.maPoints.map((point) =>
        point === null
          ? null
          : ([point[0] * stretch, point[1], point[2]] as const),
      ),
    [projection.maPoints, stretch],
  );
  const segments = useMemo(() => contiguousSegments(maPoints), [maPoints]);
  const labels = useMemo<MaLabel[]>(() => {
    const result: MaLabel[] = [];
    const total = projection.sampled.length;
    const newest = projection.sampled[total - 1];
    const newestPoint = maPoints[total - 1];

    if (newest?.ma !== null && newest?.ma !== undefined && newestPoint) {
      result.push({
        position: [newestPoint[0], 0.55, newestPoint[2]],
        value: newest.ma,
      });
    }

    for (let sample = 1; sample <= 5; sample += 1) {
      const ageIndex = Math.round((sample / 6) * (total - 1));
      const index = total - 1 - ageIndex;
      const point = projection.sampled[index];
      const maPoint = maPoints[index];
      if (point?.ma !== null && point?.ma !== undefined && maPoint) {
        result.push({
          position: [maPoint[0], 0.55, maPoint[2]],
          value: point.ma,
        });
      }
    }

    return result;
  }, [maPoints, projection.sampled]);
  const farLabel = useMemo(() => {
    const point = maPoints.find((candidate) => candidate !== null);
    return point
      ? ([point[0], 2, point[2]] as [number, number, number])
      : null;
  }, [maPoints]);

  if (segments.length === 0) return null;

  const labelOpacity = 1 - Math.max(0, Math.min(1, zoomT)) * 0.5;
  const farLabelOpacity =
    1 - Math.max(0, Math.min(1, zoomT)) * 0.75;

  return (
    <group>
      {segments.map((segment, index) => (
        <group key={`${index}-${segment[0]?.[2] ?? 0}`}>
          <Line
            points={segment}
            color="#facc15"
            lineWidth={9}
            transparent
            opacity={0.2}
            toneMapped={false}
            depthTest={false}
            depthWrite={false}
            renderOrder={MA_GLOW_ORDER}
          />
          <Line
            points={segment}
            color="#facc15"
            lineWidth={3.6}
            dashed
            dashSize={Math.max(projection.stepZ * 1.6, 1.2)}
            gapSize={Math.max(projection.stepZ * 0.9, 0.7)}
            dashScale={1}
            transparent
            toneMapped={false}
            depthTest={false}
            depthWrite={false}
            renderOrder={MA_LINE_ORDER}
          />
        </group>
      ))}
      {labels.map((label, index) => (
        <Html
          key={`${index}-${label.position[2]}`}
          position={label.position}
          distanceFactor={22}
          center
          occlude={false}
          style={{ opacity: labelOpacity, pointerEvents: "none" }}
        >
          <div className="bp-ma-label" aria-hidden="true">{formatPrice(label.value)}</div>
        </Html>
      ))}
      {farLabel ? (
        <Html
          position={farLabel}
          center
          distanceFactor={28}
          style={{ opacity: farLabelOpacity, pointerEvents: "none" }}
        >
          <div
            aria-hidden="true"
            style={{
              fontFamily: "IBM Plex Sans, sans-serif",
              fontSize: 9,
              letterSpacing: "0.18em",
              color: "#facc15",
              textTransform: "uppercase",
              textAlign: "center",
              textShadow: "0 1px 4px rgba(0,0,0,0.9)",
              whiteSpace: "nowrap",
            }}
          >
            MA Bearing
            <br />
            <span style={{ fontSize: 11, opacity: 0.85 }}>
              ({maPeriod} period)
            </span>
          </div>
        </Html>
      ) : null}
    </group>
  );
}

export default MaBearing;
