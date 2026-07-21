import { Line } from "@react-three/drei";
import { useMemo } from "react";
import * as THREE from "three";

import type { ProjectedNavigatorOcean } from "./types";

type WakeProps = Readonly<{
  projection: ProjectedNavigatorOcean;
  viewT: number;
}>;

function chartStretch(viewT: number): number {
  return 1 + Math.max(0, Math.min(1, viewT)) * 7;
}

/**
 * The wake is a visual projection of supplied closes. Per-vertex color is only
 * a comparison with the supplied MA at the same observation; it is not a signal.
 */
export function Wake({ projection, viewT }: WakeProps) {
  const stretch = chartStretch(viewT);
  const points = useMemo(
    () => projection.wakePoints.map(([x, y, z]) => [x * stretch, y, z] as [number, number, number]),
    [projection.wakePoints, stretch],
  );
  const colors = useMemo(
    () => projection.wakeColors.map((color) => new THREE.Color(color).toArray() as [number, number, number]),
    [projection.wakeColors],
  );
  const glowColors = useMemo(
    () => projection.wakeColors.map((color) => new THREE.Color(color).multiplyScalar(0.55).toArray() as [number, number, number]),
    [projection.wakeColors],
  );
  const foam = useMemo(
    () => points.filter((_, index) => index % 8 === 0),
    [points],
  );

  if (points.length < 2) return null;

  return (
    <group>
      <Line points={points} vertexColors={glowColors} lineWidth={11} transparent opacity={0.36} toneMapped={false} />
      <Line points={points} vertexColors={colors} lineWidth={4.5} toneMapped={false} />
      {foam.map((point, index) => (
        <mesh key={`${index}-${point[2]}`} position={[point[0], 0.28, point[2]]}>
          <sphereGeometry args={[0.13, 6, 6]} />
          <meshBasicMaterial color="#e9f4f5" transparent opacity={0.42} toneMapped={false} />
        </mesh>
      ))}
    </group>
  );
}
