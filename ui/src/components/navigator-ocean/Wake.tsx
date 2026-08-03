import { Line } from "@react-three/drei";
import { useMemo } from "react";
import * as THREE from "three";

import { chartStretchX } from "./projection";
import {
  WAKE_FOAM_ORDER,
  WAKE_GLOW_ORDER,
  WAKE_LINE_ORDER,
} from "./renderOrder";
import type { ProjectedNavigatorOcean } from "./types";

export type WakeProps = Readonly<{
  projection: ProjectedNavigatorOcean;
  viewT: number;
}>;

/**
 * Price-history wake in ship-centred world space. The component only renders
 * the supplied projection; it never fetches, derives, or mutates market data.
 */
export function Wake({ projection, viewT }: WakeProps) {
  const stretch = useMemo(
    () => Math.round(chartStretchX(viewT) * 4) / 4,
    [viewT],
  );
  const wakePoints = useMemo(
    () =>
      projection.wakePoints.map(
        ([x, y, z]) => [x * stretch, y, z] as [number, number, number],
      ),
    [projection.wakePoints, stretch],
  );
  const lineColors = useMemo(
    () =>
      projection.wakeColors.map(
        (color) => new THREE.Color(color).toArray() as [number, number, number],
      ),
    [projection.wakeColors],
  );
  const glowColors = useMemo(
    () =>
      projection.wakeColors.map(
        (color) =>
          new THREE.Color(color)
            .multiplyScalar(0.6)
            .toArray() as [number, number, number],
      ),
    [projection.wakeColors],
  );
  const foamPoints = useMemo(
    () =>
      wakePoints
        .filter((_, index) => index % 6 === 0)
        .map(([x, _y, z]) => [x, 0.26, z] as [number, number, number]),
    [wakePoints],
  );

  if (wakePoints.length < 2) return null;

  return (
    <group>
      <Line
        points={wakePoints}
        vertexColors={glowColors}
        lineWidth={14}
        transparent
        opacity={0.45}
        toneMapped={false}
        depthTest={false}
        depthWrite={false}
        renderOrder={WAKE_GLOW_ORDER}
      />
      <Line
        points={wakePoints}
        vertexColors={lineColors}
        lineWidth={6}
        transparent
        toneMapped={false}
        depthTest={false}
        depthWrite={false}
        renderOrder={WAKE_LINE_ORDER}
      />
      {foamPoints.map((point, index) => (
        <mesh
          key={`${index}-${point[2]}`}
          position={point}
          renderOrder={WAKE_FOAM_ORDER}
        >
          <sphereGeometry args={[0.15, 6, 6]} />
          <meshBasicMaterial
            color="#e6eef7"
            transparent
            opacity={0.5}
            toneMapped={false}
            depthTest={false}
            depthWrite={false}
          />
        </mesh>
      ))}
    </group>
  );
}

export default Wake;
