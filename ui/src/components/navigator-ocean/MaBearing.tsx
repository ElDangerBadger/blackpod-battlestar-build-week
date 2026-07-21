import { Line } from "@react-three/drei";
import { useMemo } from "react";

import type { NavigatorOceanVector, ProjectedNavigatorOcean } from "./types";

type MaBearingProps = Readonly<{
  projection: ProjectedNavigatorOcean;
  viewT: number;
}>;

function contiguousSegments(points: readonly (NavigatorOceanVector | null)[]): [number, number, number][][] {
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
export function MaBearing({ projection, viewT }: MaBearingProps) {
  const stretch = 1 + Math.max(0, Math.min(1, viewT)) * 7;
  const segments = useMemo(
    () => contiguousSegments(projection.maPoints.map((point) => (
      point === null ? null : [point[0] * stretch, point[1], point[2]]
    ))),
    [projection.maPoints, stretch],
  );

  return (
    <group>
      {segments.map((segment, index) => (
        <group key={`${index}-${segment[0]?.[2] ?? 0}`}>
          <Line points={segment} color="#f4cb53" lineWidth={8} transparent opacity={0.18} toneMapped={false} />
          <Line
            points={segment}
            color="#f4cb53"
            lineWidth={3.2}
            dashed
            dashSize={Math.max(projection.stepZ * 1.25, 1.2)}
            gapSize={Math.max(projection.stepZ * 0.72, 0.7)}
            toneMapped={false}
          />
        </group>
      ))}
    </group>
  );
}
