import { Line } from '@react-three/drei';
import { useMemo } from 'react';
import * as THREE from 'three';
import type { ProjectedScene } from './projection';
import { chartStretchX } from './projection';
import { useMarket } from '../store';

interface WakeProps {
  projection: ProjectedScene;
}

/**
 * Wake = the absolute price-history polyline in world space.
 * Most recent bar is at the ship (X=0, Z=0); older bars at +Z, with X reflecting
 * their absolute price relative to the current price.
 *
 * The wake's lateral distance from the MA line at any z is exactly (price - MA)
 * at that bar — the metaphor is geometrically faithful.
 */
export default function Wake2({ projection }: WakeProps) {
  const { wakeColors } = projection;
  const viewT = useMarket((s) => s.viewT);

  // Apply the chart-stretch to the price (X) axis. Quantize the factor so the
  // Line2 geometry only rebuilds a limited number of times during a zoom.
  const stretch = useMemo(
    () => Math.round(chartStretchX(viewT) * 4) / 4,
    [viewT],
  );
  const wakePoints = useMemo(
    () =>
      projection.wakePoints.map(
        (p) => [p[0] * stretch, p[1], p[2]] as [number, number, number],
      ),
    [projection.wakePoints, stretch],
  );

  const colorVec = useMemo(
    () => wakeColors.map((c) => new THREE.Color(c).toArray() as [number, number, number]),
    [wakeColors],
  );
  const glowColors = useMemo(
    () =>
      wakeColors.map((c) =>
        new THREE.Color(c).multiplyScalar(0.6).toArray() as [number, number, number],
      ),
    [wakeColors],
  );

  // Foam dots sampled along the wake
  const foam = useMemo(() => {
    const out: [number, number, number][] = [];
    for (let i = 0; i < wakePoints.length; i += 6) {
      const p = wakePoints[i];
      out.push([p[0], 0.26, p[2]]);
    }
    return out;
  }, [wakePoints]);

  if (wakePoints.length < 2) return null;

  return (
    <group>
      {/* Glow halo */}
      <Line
        points={wakePoints}
        vertexColors={glowColors}
        lineWidth={14}
        transparent
        opacity={0.45}
        toneMapped={false}
      />
      {/* Main vertex-colored line */}
      <Line
        points={wakePoints}
        vertexColors={colorVec}
        lineWidth={6}
        toneMapped={false}
      />
      {/* Foam dots */}
      {foam.map((p, i) => (
        <mesh key={i} position={p}>
          <sphereGeometry args={[0.15, 6, 6]} />
          <meshBasicMaterial
            color="#e6eef7"
            transparent
            opacity={0.5}
            toneMapped={false}
          />
        </mesh>
      ))}
    </group>
  );
}