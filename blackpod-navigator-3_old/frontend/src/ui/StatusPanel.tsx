import { useMarket } from '../store';

function fmt(v: number | null | undefined, digits = 2): string {
  if (v == null || isNaN(v)) return '—';
  if (Math.abs(v) >= 10000) return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
  return v.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

const VOL_LABEL: Record<string, string> = {
  glass: 'Glass',
  gentle: 'Gentle Waves',
  moderate: 'Moderate Chop',
  high: 'Whitecaps',
  storm: 'Storm Seas',
};

const VOL_COLOR: Record<string, string> = {
  glass: '#60a5fa',
  gentle: '#67e8f9',
  moderate: '#facc15',
  high: '#f97316',
  storm: '#ef4444',
};

export default function StatusPanel() {
  const data = useMarket((s) => s.data);
  const loading = useMarket((s) => s.loading);
  const error = useMarket((s) => s.error);

  if (!data && !loading && !error) {
    return (
      <div className="bp-panel" style={{ padding: 14 }}>
        <span className="bp-panel-title">Current Status</span>
        <div style={{ fontSize: 12, color: 'var(--bp-text-dim)', marginTop: 10 }}>Select a vessel from the harbor.</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bp-panel" style={{ padding: 14, borderColor: 'rgba(239,68,68,0.4)' }}>
        <span className="bp-panel-title" style={{ color: '#ef4444' }}>Error</span>
        <div style={{ fontSize: 12, color: 'var(--bp-text-dim)', marginTop: 10, lineHeight: 1.5 }}>{error}</div>
      </div>
    );
  }

  const s = data?.summary;
  const posClass = s?.position === 'above' ? 'green' : s?.position === 'below' ? 'red' : 'gray';
  const slopeClass = (s?.trend_slope_pct ?? 0) > 0.05 ? 'green' : (s?.trend_slope_pct ?? 0) < -0.05 ? 'red' : 'gray';

  return (
    <div className="bp-panel" style={{ padding: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span className="bp-panel-title">Current Status</span>
        {data && (
          <span style={{ fontSize: 10.5, color: 'var(--bp-text-faint)', letterSpacing: '0.1em' }}>
            {data.symbol} · {data.timeframe.toUpperCase()}
          </span>
        )}
      </div>
      {data?.data?.stale && (
        <div className="bp-stale-badge" title={`Last good data is ${Math.round((data.data.age_seconds ?? 0) / 60)} min old (live source unavailable)`}>
          ⚠ Showing last-known data — live feed unavailable
        </div>
      )}
      <div className="bp-divider" />
      <div className="bp-kv">
        <span className="k">Price</span>
        <span className="v yellow" style={{ fontSize: 15, fontWeight: 600 }}>{fmt(s?.last_price)}</span>
      </div>
      <div className="bp-kv">
        <span className="k">MA ({data?.ma_period})</span>
        <span className="v">{fmt(s?.last_ma)}</span>
      </div>
      <div className="bp-kv">
        <span className="k">Difference</span>
        <span className={`v ${posClass}`}>
          {s && s.pct_vs_ma >= 0 ? '+' : ''}
          {fmt(s ? s.last_price - (s.last_ma ?? 0) : 0)}
        </span>
      </div>
      <div className="bp-kv">
        <span className="k">% vs MA</span>
        <span className={`v ${posClass}`}>
          {s && s.pct_vs_ma >= 0 ? '+' : ''}
          {fmt(s?.pct_vs_ma)}%
        </span>
      </div>
      <div className="bp-kv">
        <span className="k">Position</span>
        <span className={`v ${posClass}`} style={{ textTransform: 'capitalize' }}>{s?.position ?? '—'} MA</span>
      </div>
      <div className="bp-kv">
        <span className="k">Trend (MA slope)</span>
        <span className={`v ${slopeClass}`}>
          {s && s.trend_slope_pct >= 0 ? '+' : ''}
          {fmt(s?.trend_slope_pct, 2)}%
        </span>
      </div>
      <div className="bp-kv">
        <span className="k">ATR</span>
        <span className="v">
          {fmt(s?.atr)} <span style={{ color: 'var(--bp-text-faint)' }}>({fmt(s?.atr_pct)}%)</span>
        </span>
      </div>
      <div className="bp-kv">
        <span className="k">Sea State</span>
        <span
          className="bp-vol-chip"
          style={{ color: VOL_COLOR[s?.volatility ?? 'gentle'], borderColor: 'rgba(255,255,255,0.12)' }}
        >
          <span className="pulse" style={{ background: VOL_COLOR[s?.volatility ?? 'gentle'] }} />
          {VOL_LABEL[s?.volatility ?? 'gentle']}
        </span>
      </div>
      {loading && (
        <div style={{ marginTop: 10, fontSize: 10.5, color: 'var(--bp-yellow)', letterSpacing: '0.15em', textTransform: 'uppercase' }}>
          ◯ Updating…
        </div>
      )}
    </div>
  );
}