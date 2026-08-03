import { useMarket } from '../store';

const CATEGORY_ORDER: Array<{ key: string; label: string }> = [
  { key: 'equity', label: 'Equities' },
  { key: 'index', label: 'Indices' },
  { key: 'commodity', label: 'Commodities' },
  { key: 'crypto', label: 'Crypto' },
];

export default function Harbor() {
  const tickers = useMarket((s) => s.tickers);
  const symbol = useMarket((s) => s.symbol);
  const setSymbol = useMarket((s) => s.setSymbol);
  const dataSymbol = useMarket((s) => s.data?.symbol);
  const position = useMarket((s) => s.data?.summary.position);

  return (
    <aside className="bp-panel bp-scroll" style={{ padding: '12px 8px', display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: '0 8px 6px 8px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span className="bp-panel-title">⚓ Harbor</span>
        <span style={{ fontSize: 10, color: 'var(--bp-text-faint)' }}>{tickers.length} vessels</span>
      </div>
      <div className="bp-divider" />
      {CATEGORY_ORDER.map((cat) => {
        const items = tickers.filter((t) => t.category === cat.key);
        if (!items.length) return null;
        return (
          <div key={cat.key} style={{ marginBottom: 6 }}>
            <div className="bp-section-label">{cat.label}</div>
            {items.map((t) => {
              const active = t.symbol === symbol;
              const showDot = active && dataSymbol === t.symbol && position;
              return (
                <div
                  key={t.symbol}
                  className={`bp-harbor-row ${active ? 'active' : ''}`}
                  onClick={() => setSymbol(t.symbol)}
                >
                  <span className="sym mono">{t.symbol}</span>
                  <span className="name">{t.name}</span>
                  <span className={`bp-dot ${showDot ? position : ''}`} />
                </div>
              );
            })}
          </div>
        );
      })}
      <div style={{ flex: 1 }} />
      <div style={{ padding: '8px 12px', fontSize: 10, color: 'var(--bp-text-faint)', letterSpacing: '0.06em' }}>
        Click a ticker to deploy that vessel into the visualization.
      </div>
    </aside>
  );
}