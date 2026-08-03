import { useMemo } from 'react';
import { Line } from '@react-three/drei';
import * as THREE from 'three';
import type { Bar } from '../types';

interface WakeProps {
  bars: Bar[];
  oceanExag: number;
  stepZ: number;
  priceToWorld: number;
}

/**
 * Wake is a 3D polyline behind the ship.
 * - Most recent bar is at z=0 (under the ship)
 * - Each older bar at z = (i) * stepZ in +Z direction (toward horizon)
 * - Lateral X offset = (close - ma_at_that_bar) * priceToWorld * oceanExag
 * - Color per segment:
 *    green if c > ma + 0.25% ma
 *    red if c < ma - 0.25% ma
 *    gray near
 */
export default function Wake({ bars, oceanExag, stepZ, priceToWorld }: WakeProps) {
  const { points, colors, foamPoints } = useMemo(() => {
    if (!bars.length) {
      return { points: [] as [number, number, number][], colors: [] as string[], foamPoints: [] as [number, number, number][] };
    }
    // Sample down to max 500 points
    const MAX = 500;
    const n = bars.length;
    const stride = Math.max(1, Math.floor(n / MAX));
    const sampled: Bar[] = [];
    for (let i = 0; i < n; i += stride) sampled.push(bars[i]);
    if (sampled[sampled.length - 1] !== bars[n - 1]) sampled.push(bars[n - 1]);

    // Order: oldest first, newest last (=ship position)
    const pts: [number, number, number][] = [];
    const cols: string[] = [];
    const foamPts: [number, number, number][] = [];
    const total = sampled.length;
    for (let i = 0; i < total; i++) {
      const b = sampled[i];
      const ageIndex = total - 1 - i; // 0 = newest (ship), total-1 = oldest
      const z = ageIndex * stepZ;
      const ma = b.ma ?? b.c;
      const diff = b.c - ma;
      const dx = diff * priceToWorld * oceanExag;
      pts.push([dx, 0.18, z]);

      const pct = ma ? (diff / ma) * 100 : 0;
      if (pct > 0.25) cols.push('#22c55e');
      else if (pct < -0.25) cols.push('#ef4444');
      else cols.push('#9ca3af');

      // Foam point (slightly above water along the trail; subset for perf)
      if (i % 6 === 0) foamPts.push([dx, 0.22, z]);
    }
    return { points: pts, colors: cols, foamPoints: foamPts };
  }, [bars, oceanExag, stepZ, priceToWorld]);

  if (points.length < 2) return null;

  return (
    <group>
      {/* Soft glow halo line under main line */}
      <Line
        points={points}
        vertexColors={colors.map((c) => new THREE.Color(c).multiplyScalar(0.6).toArray() as [number, number, number])}
        lineWidth={14}
        transparent
        opacity={0.5}
        toneMapped={false}
      />
      {/* Main wake line with vertex colors */}
      <Line
        points={points}
        vertexColors={colors.map((c) => new THREE.Color(c).toArray() as [number, number, number])}
        lineWidth={6}
        toneMapped={false}
      />
      {/* Foam dots */}
      {foamPoints.map((p, i) => (
        <mesh key={i} position={p}>
          <sphereGeometry args={[0.16, 6, 6]} />
          <meshBasicMaterial color="#e6eef7" transparent opacity={0.55} toneMapped={false} />
        </mesh>
      ))}
    </group>
  );
}