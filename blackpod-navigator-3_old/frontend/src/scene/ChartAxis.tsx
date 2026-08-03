import { Html } from '@react-three/drei';
import type { Bar } from '../types';

interface ChartAxisProps {
  bars: Bar[];
  stepZ: number;
  priceToWorld: number;
  zoomT: number;
}

/**
 * When zooming toward top-down, reveal price axis labels at the right edge of the chart
 * (positive X side) showing the dollar values that correspond to the wake's lateral offset.
 *
 * These labels live in world space; we place them at the far end of the wake (max z) and
 * scale opacity with zoomT. They communicate "this is now a chart".
 */
export default function ChartAxis({ bars, stepZ, priceToWorld, zoomT }: ChartAxisProps) {
  if (zoomT < 0.55) return null;
  if (!bars.length) return null;

  const opacity = (zoomT - 0.55) / 0.45;
  const last = bars[bars.length - 1];
  const lastMa = last.ma ?? last.c;
  const lastPrice = last.c;

  // Y-axis price ticks centered on the MA, ±N steps
  const atr = last.atr ?? Math.abs(lastPrice * 0.01);
  const stepPrice = Math.max(atr * 2, lastPrice * 0.005);
  const ticks: { price: number; dx: number }[] = [];
  for (let i = -4; i <= 4; i++) {
    const price = lastMa + i * stepPrice;
    const dx = (price - lastMa) * priceToWorld;
    ticks.push({ price, dx });
  }

  // Z range: place axis at far end of wake (largest Z visible)
  const farZ = (Math.min(bars.length, 500) - 1) * stepZ;

  return (
    <group>
      {ticks.map((tk, i) => (
        <Html
          key={i}
          position={[tk.dx, 0.5, 0]}
          center
          distanceFactor={28}
          style={{ opacity, transition: 'opacity 200ms ease', pointerEvents: 'none' }}
        >
          <div className="bp-axis-label">{formatPrice(tk.price)}</div>
        </Html>
      ))}
      {/* Current price marker at ship position */}
      <Html
        position={[(lastPrice - lastMa) * priceToWorld, 0.5, 0]}
        center
        distanceFactor={26}
        style={{ opacity, transition: 'opacity 200ms ease', pointerEvents: 'none' }}
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
          {formatPrice(lastPrice)}
        </div>
      </Html>
      {/* Far horizon Z label (oldest date marker) */}
      <Html
        position={[0, 0.5, farZ + 6]}
        center
        distanceFactor={36}
        style={{ opacity, pointerEvents: 'none' }}
      >
        <div className="bp-axis-label" style={{ opacity: 0.6 }}>OLDEST →</div>
      </Html>
    </group>
  );
}

function formatPrice(v: number): string {
  if (v >= 10000) return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (v >= 100) return v.toLocaleString(undefined, { maximumFractionDigits: 1 });
  return v.toFixed(2);
}