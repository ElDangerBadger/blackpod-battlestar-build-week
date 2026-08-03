import { useMemo } from 'react';
import { Html, Line } from '@react-three/drei';
import type { Bar } from '../types';

interface MaBearingProps {
  bars: Bar[];
  stepZ: number;
  maPeriod: number;
  zoomT: number;
}

/**
 * Yellow dashed line going from the ship (z=0) straight to the horizon (+Z),
 * with floating price labels showing MA values at intervals.
 *
 * Because the wake's lateral position is *relative to the MA*, the MA line itself
 * runs perfectly straight down the world's centerline (x=0). The wake meanders
 * left/right around it — exactly matching the reference image.
 */
export default function MaBearing({ bars, stepZ, maPeriod, zoomT }: MaBearingProps) {
  const { linePoints, labels } = useMemo(() => {
    if (!bars.length) return { linePoints: [] as [number, number, number][], labels: [] as { z: number; ma: number }[] };

    // Sample down to ~500 like wake to stay aligned
    const MAX = 500;
    const n = bars.length;
    const stride = Math.max(1, Math.floor(n / MAX));
    const sampled: Bar[] = [];
    for (let i = 0; i < n; i += stride) sampled.push(bars[i]);
    if (sampled[sampled.length - 1] !== bars[n - 1]) sampled.push(bars[n - 1]);

    const total = sampled.length;
    const pts: [number, number, number][] = [];
    for (let i = 0; i < total; i++) {
      const ageIndex = total - 1 - i;
      pts.push([0, 0.2, ageIndex * stepZ]);
    }

    // Labels: 4 evenly spaced along the line, plus the current MA at the ship (z=0).
    const labelCount = 5;
    const lbls: { z: number; ma: number }[] = [];
    // Current MA (right at the ship)
    const lastBar = sampled[total - 1];
    if (lastBar && lastBar.ma != null) {
      lbls.push({ z: 0, ma: lastBar.ma });
    }
    for (let k = 1; k <= labelCount; k++) {
      const ageIndex = Math.round((k / (labelCount + 1)) * (total - 1));
      const sampledIdx = total - 1 - ageIndex;
      const b = sampled[sampledIdx];
      if (b && b.ma != null) {
        lbls.push({ z: ageIndex * stepZ, ma: b.ma });
      }
    }
    return { linePoints: pts, labels: lbls };
  }, [bars, stepZ]);

  if (linePoints.length < 2) return null;

  return (
    <group>
      {/* Glow underlay */}
      <Line
        points={linePoints}
        color="#facc15"
        lineWidth={8}
        transparent
        opacity={0.18}
        toneMapped={false}
      />
      {/* Main dashed yellow line */}
      <Line
        points={linePoints}
        color="#facc15"
        lineWidth={3.2}
        dashed
        dashSize={1.6}
        gapSize={1.0}
        dashScale={1}
        toneMapped={false}
      />
      {/* Price labels along the line — anchored to the right of the yellow line.
          Each label sits at increasing lateral X offset to spread the column visually
          and prevent stacking at the vanishing point. */}
      {labels.map((lbl, i) => {
        // First label (i=0) sits very close to the line near the ship; subsequent
        // labels along the receding line use a constant world offset, then
        // distanceFactor handles their visual sizing.
        return (
          <Html
            key={i}
            position={[3, 0.7, lbl.z]}
            distanceFactor={20}
            center
            occlude={false}
            style={{
              opacity: 1 - zoomT * 0.55,
              transition: 'opacity 200ms ease',
              pointerEvents: 'none',
            }}
          >
            <div className="bp-ma-label">{formatPrice(lbl.ma)}</div>
          </Html>
        );
      })}
      {/* MA period marker at far end (horizon tag) */}
      {linePoints.length > 0 && (
        <Html
          position={[0, 2, linePoints[0][2]]}
          center
          style={{
            opacity: 1 - zoomT * 0.7,
            transition: 'opacity 200ms ease',
          }}
        >
          <div
            style={{
              fontFamily: 'IBM Plex Sans',
              fontSize: 9,
              letterSpacing: '0.18em',
              color: '#facc15',
              textTransform: 'uppercase',
              textAlign: 'center',
              textShadow: '0 1px 4px rgba(0,0,0,0.9)',
              whiteSpace: 'nowrap',
            }}
          >
            MA Bearing<br />
            <span style={{ fontSize: 11, opacity: 0.85 }}>({maPeriod} period)</span>
          </div>
        </Html>
      )}
    </group>
  );
}

function formatPrice(v: number): string {
  if (v >= 1000) return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (v >= 100) return v.toLocaleString(undefined, { maximumFractionDigits: 1 });
  return v.toFixed(2);
}