import { Html } from '@react-three/drei';
import type { ProjectedScene } from './projection';
import { chartStretchX } from './projection';
import { useMarket } from '../store';

interface ChartAxisProps {
  projection: ProjectedScene;
  zoomT: number;
}

/**
 * Right-side price axis revealed as the camera approaches top-down.
 *
 * In the new ship-anchored coordinate system, the ship is at X=0 = price_now.
 * So price ticks are placed at X = (price - price_now) * priceToWorld around X=0.
 */
export default function ChartAxis2({ projection, zoomT }: ChartAxisProps) {
  const viewT = useMarket((s) => s.viewT);
  if (zoomT < 0.55) return null;
  const { sampled, priceToWorld, priceNow, zSpan, stepZ } = projection;
  if (!sampled.length) return null;
  const opacity = (zoomT - 0.55) / 0.45;
  const stretch = chartStretchX(viewT);
  const last = sampled[sampled.length - 1];
  const atr = last.atr ?? Math.abs(priceNow * 0.01);
  const step = Math.max(atr * 2, priceNow * 0.005);

  // Ticks centered on priceNow (X stretched to match the chart-stretched wake/MA)
  const ticks: { price: number; dx: number }[] = [];
  for (let i = -4; i <= 4; i++) {
    const price = priceNow + i * step;
    const dx = (price - priceNow) * priceToWorld * stretch;
    ticks.push({ price, dx });
  }

  // Place ticks just in front of the ship (small +Z) so they read as the
  // right-hand price axis of the chart (the ship/current price sits on the right).
  const axisZ = Math.min(zSpan * 0.05, stepZ * 8);

  return (
    <group>
      {ticks.map((tk, i) => (
        <Html
          key={i}
          position={[tk.dx, 0.55, axisZ]}
          center
          distanceFactor={28}
          style={{ opacity, transition: 'opacity 200ms ease', pointerEvents: 'none' }}
        >
          <div className="bp-axis-label">{formatPrice(tk.price)}</div>
        </Html>
      ))}
      {/* Current price chip at the ship */}
      <Html
        position={[0, 0.55, 0]}
        center
        distanceFactor={24}
        style={{ opacity, pointerEvents: 'none' }}
      >
        <div
          style={{
            fontFamily: 'IBM Plex Mono',
            fontSize: 10,
            color: '#facc15',
            background: 'rgba(13,18,24,0.85)',
            border: '1px solid rgba(250,204,21,0.4)',
            padding: '2px 6px',
            borderRadius: 4,
            whiteSpace: 'nowrap',
          }}
        >
          {formatPrice(priceNow)}
        </div>
      </Html>
      <Html
        position={[0, 0.5, -(zSpan + 12)]}
        center
        distanceFactor={36}
        style={{ opacity, pointerEvents: 'none' }}
      >
        <div className="bp-axis-label" style={{ opacity: 0.6 }}>← OLDEST</div>
      </Html>
    </group>
  );
}

function formatPrice(v: number): string {
  if (v >= 10000) return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (v >= 100) return v.toLocaleString(undefined, { maximumFractionDigits: 1 });
  return v.toFixed(2);
}