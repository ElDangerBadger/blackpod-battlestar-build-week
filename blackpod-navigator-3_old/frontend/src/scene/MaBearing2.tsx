import { Html, Line } from '@react-three/drei';
import { useMemo } from 'react';
import type { ProjectedScene } from './projection';
import { chartStretchX } from './projection';
import { useMarket } from '../store';

interface MaBearingProps {
  projection: ProjectedScene;
  maPeriod: number;
  zoomT: number;
}

/**
 * Yellow dashed MA line — now a **curving polyline** in world space.
 *
 * Each vertex sits at:
 *   ( (ma[i] - price_now) * priceToWorld,  y,  ageIndex * stepZ )
 *
 * Therefore the line bows left when the MA is rising (older MA values were lower
 * than the current MA → larger negative offsets from price_now if price>MA) and
 * bows right when the MA is falling. This visually encodes trend curvature.
 */
export default function MaBearing2({ projection, maPeriod, zoomT }: MaBearingProps) {
  const { sampled, stepZ } = projection;
  const viewT = useMarket((s) => s.viewT);

  // Chart-stretch the price (X) axis, quantized to limit geometry rebuilds.
  const stretch = useMemo(
    () => Math.round(chartStretchX(viewT) * 4) / 4,
    [viewT],
  );
  const maPoints = useMemo(
    () =>
      projection.maPoints.map((p) =>
        p ? ([p[0] * stretch, p[1], p[2]] as [number, number, number]) : null,
      ),
    [projection.maPoints, stretch],
  );

  // Collapse null gaps: extract contiguous polylines so that bars without MA
  // (early period before window fills) don't draw straight lines through origin.
  const segments = useMemo(() => {
    const segs: [number, number, number][][] = [];
    let cur: [number, number, number][] = [];
    for (const p of maPoints) {
      if (p) {
        cur.push(p);
      } else if (cur.length > 1) {
        segs.push(cur);
        cur = [];
      } else {
        cur = [];
      }
    }
    if (cur.length > 1) segs.push(cur);
    return segs;
  }, [maPoints]);

  // Label positions — sample 5 MA values along the polyline at evenly spaced ages,
  // plus the current MA at the ship.
  const labels = useMemo(() => {
    const total = sampled.length;
    const lbls: { pos: [number, number, number]; ma: number }[] = [];
    const last = sampled[total - 1];
    if (last && last.ma != null && maPoints[total - 1]) {
      const p = maPoints[total - 1]!;
      lbls.push({ pos: [p[0], 0.55, p[2]], ma: last.ma });
    }
    for (let k = 1; k <= 5; k++) {
      const ageIndex = Math.round((k / 6) * (total - 1));
      const idx = total - 1 - ageIndex;
      const b = sampled[idx];
      const mp = maPoints[idx];
      if (b && b.ma != null && mp) {
        lbls.push({ pos: [mp[0], 0.55, mp[2]], ma: b.ma });
      }
    }
    return lbls;
  }, [sampled, maPoints]);

  // Far-horizon label (at the furthest valid MA point).
  const farLabel = useMemo(() => {
    for (let i = 0; i < maPoints.length; i++) {
      const p = maPoints[i];
      if (p) return { pos: [p[0], 2, p[2]] as [number, number, number] };
    }
    return null;
  }, [maPoints]);

  if (!segments.length) return null;

  return (
    <group>
      {segments.map((seg, si) => (
        <group key={si}>
          {/* Glow underlay */}
          <Line
            points={seg}
            color="#facc15"
            lineWidth={9}
            transparent
            opacity={0.2}
            toneMapped={false}
          />
          {/* Dashed yellow MA line */}
          <Line
            points={seg}
            color="#facc15"
            lineWidth={3.6}
            dashed
            dashSize={Math.max(stepZ * 1.6, 1.2)}
            gapSize={Math.max(stepZ * 0.9, 0.7)}
            dashScale={1}
            toneMapped={false}
          />
        </group>
      ))}
      {labels.map((lbl, i) => (
        <Html
          key={i}
          position={lbl.pos}
          distanceFactor={22}
          center
          occlude={false}
          style={{
            opacity: 1 - zoomT * 0.5,
            transition: 'opacity 200ms ease',
            pointerEvents: 'none',
          }}
        >
          <div className="bp-ma-label">{formatPrice(lbl.ma)}</div>
        </Html>
      ))}
      {farLabel && (
        <Html
          position={farLabel.pos}
          center
          distanceFactor={28}
          style={{
            opacity: 1 - zoomT * 0.75,
            transition: 'opacity 200ms ease',
            pointerEvents: 'none',
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
  if (v >= 10000) return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (v >= 1000)  return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (v >= 100)   return v.toLocaleString(undefined, { maximumFractionDigits: 1 });
  return v.toFixed(2);
}