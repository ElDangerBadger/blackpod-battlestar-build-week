import { useMarket } from '../store';

const TICKS = [
  { t: 0,    label: 'Close' },
  { t: 0.30, label: 'Far' },
  { t: 0.65, label: 'High' },
  { t: 1,    label: 'Chart' },
];

export default function ZoomStrip() {
  const zoomT = useMarket((s) => s.zoomT);
  const setZoomT = useMarket((s) => s.setZoomT);

  let label = 'PERSPECTIVE (CLOSE)';
  if (zoomT > 0.85) label = 'TOP-DOWN (CHART)';
  else if (zoomT > 0.5) label = 'HIGH ANGLE';
  else if (zoomT > 0.2) label = 'FAR PERSPECTIVE';

  return (
    <div className="bp-panel bp-zoom-strip">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span className="bp-panel-title" style={{ fontSize: 9.5 }}>Vantage</span>
        <span className="mono" style={{ fontSize: 10, color: 'var(--bp-text-dim)' }}>{label}</span>
      </div>
      <input
        type="range"
        className="bp-slider"
        min={0}
        max={1}
        step={0.001}
        value={zoomT}
        onChange={(e) => setZoomT(parseFloat(e.target.value))}
        style={{ width: '100%' }}
      />
      <div className="bp-zoom-ticks">
        {TICKS.map((t) => (
          <button
            key={t.t}
            onClick={() => setZoomT(t.t)}
            style={{
              background: 'transparent',
              border: 'none',
              color: Math.abs(zoomT - t.t) < 0.05 ? 'var(--bp-yellow)' : 'inherit',
              fontFamily: 'IBM Plex Sans',
              fontSize: 8.5,
              letterSpacing: '0.12em',
              cursor: 'pointer',
              padding: 2,
              textTransform: 'uppercase',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>
    </div>
  );
}