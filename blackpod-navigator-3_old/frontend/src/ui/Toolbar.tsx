import { useMarket } from '../store';
import type { MaPeriod, Timeframe } from '../types';

const TIMEFRAMES: { v: Timeframe; label: string }[] = [
  { v: '1h',  label: '1H' },
  { v: '1d',  label: 'D'  },
  { v: '1wk', label: 'W'  },
];

const MA_PERIODS: MaPeriod[] = [20, 50, 100, 200, 250];

export default function Toolbar() {
  const timeframe = useMarket((s) => s.timeframe);
  const maPeriod = useMarket((s) => s.maPeriod);
  const oceanExag = useMarket((s) => s.oceanExag);
  const setTimeframe = useMarket((s) => s.setTimeframe);
  const setMaPeriod = useMarket((s) => s.setMaPeriod);
  const setOceanExag = useMarket((s) => s.setOceanExag);

  return (
    <header className="bp-header">
      <div className="bp-logo">
        <div className="mark">⛵</div>
        <div>
          BLACKPOD <span style={{ color: 'var(--bp-yellow)' }}>NAVIGATOR</span>
          <div className="codename">FINANCIAL OCEAN · MVP v0.1</div>
        </div>
      </div>
      <div style={{ flex: 1 }} />

      <div className="bp-toolbar-group">
        <span className="label">Timeframe</span>
        {TIMEFRAMES.map((tf) => (
          <button
            key={tf.v}
            className={`bp-pill ${timeframe === tf.v ? 'active' : ''}`}
            onClick={() => setTimeframe(tf.v)}
          >
            {tf.label}
          </button>
        ))}
      </div>

      <div className="bp-toolbar-group">
        <span className="label">Moving Avg</span>
        {MA_PERIODS.map((p) => (
          <button
            key={p}
            className={`bp-pill ${maPeriod === p ? 'active' : ''}`}
            onClick={() => setMaPeriod(p)}
          >
            {p}
          </button>
        ))}
      </div>

      <div className="bp-toolbar-group">
        <span className="label">Ocean Exag.</span>
        <input
          type="range"
          className="bp-slider"
          min={0.2}
          max={2.5}
          step={0.05}
          value={oceanExag}
          onChange={(e) => setOceanExag(parseFloat(e.target.value))}
        />
        <span className="mono" style={{ fontSize: 11, color: 'var(--bp-text-dim)', width: 32 }}>
          {oceanExag.toFixed(1)}×
        </span>
      </div>
    </header>
  );
}