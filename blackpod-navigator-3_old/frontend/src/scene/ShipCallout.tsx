import { Html } from '@react-three/drei';
import type { OhlcSummary } from '../types';

interface ShipCalloutProps {
  summary: OhlcSummary;
  symbol: string;
  zoomT: number;
}

export default function ShipCallout({ summary, symbol, zoomT }: ShipCalloutProps) {
  if (zoomT > 0.6) return null;
  const opacity = Math.max(0, 1 - zoomT / 0.6);
  const cls =
    summary.position === 'above' ? 'green'
      : summary.position === 'below' ? 'red'
        : 'gray';

  return (
    <Html
      position={[-5.5, 2.5, 1.5]}
      distanceFactor={7}
      style={{ opacity, transition: 'opacity 150ms ease', pointerEvents: 'none' }}
    >
      <div className="bp-ship-callout">
        <div className="lbl">{symbol} · PRICE (SHIP)</div>
        <div className="price">{formatPrice(summary.last_price)}</div>
        <div className={`pct ${cls}`}>
          {summary.pct_vs_ma >= 0 ? '+' : ''}
          {summary.pct_vs_ma.toFixed(2)}%
        </div>
        <div className={`pos ${cls}`}>
          {summary.position === 'above' ? 'Above MA' : summary.position === 'below' ? 'Below MA' : 'Near MA'}
        </div>
      </div>
    </Html>
  );
}

function formatPrice(v: number): string {
  if (v >= 10000) return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (v >= 100) return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return v.toFixed(2);
}