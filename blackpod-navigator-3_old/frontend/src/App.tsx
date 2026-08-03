import { useEffect, lazy, Suspense } from 'react';
import './styles/app.css';
import Harbor from './ui/Harbor';
import StatusPanel from './ui/StatusPanel';
import HowToRead from './ui/HowToRead';
import Toolbar from './ui/Toolbar';
import ZoomStrip from './ui/ZoomStrip';
import { useMarket } from './store';

// The 3D scene (Three.js / R3F) is the heaviest part of the bundle.
// Lazy-load it so the initial HTML/CSS shell paints fast and the WebGL
// runtime is fetched in a separate chunk.
const Scene = lazy(() => import('./scene/Scene2'));

export default function App() {
  const initTickers = useMarket((s) => s.initTickers);
  const fetchData = useMarket((s) => s.fetch);
  const loading = useMarket((s) => s.loading);
  const data = useMarket((s) => s.data);

  useEffect(() => {
    void initTickers();
    void fetchData();
  }, [initTickers, fetchData]);

  return (
    <div className="bp-app">
      <Toolbar />
      <main className="bp-main">
        <Harbor />
        <section className="bp-scene-host">
          <Suspense
            fallback={<div className="bp-loading-overlay">▢ Preparing the ocean…</div>}
          >
            <Scene />
          </Suspense>
          <ZoomStrip />
          {loading && !data && (
            <div className="bp-loading-overlay">▢ Charting course…</div>
          )}
          <div className="bp-hint">
            Scroll to zoom · Left-drag to pan · Right-drag to rotate · Double-click to reset
          </div>
        </section>
        <aside className="bp-scroll" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <StatusPanel />
          <HowToRead />
          <Disclaimer />
        </aside>
      </main>
      <footer className="bp-footer">
        Not investment advice · Visualization for educational purposes only ·
        Data may be delayed, synthetic, or inaccurate.
      </footer>
    </div>
  );
}

function Disclaimer() {
  const data = useMarket((s) => s.data);
  const text =
    data?.disclaimer ??
    'BlackPod Navigator is a market-data visualization for educational and ' +
      'informational purposes only. It is not investment advice. Data may be ' +
      'delayed, synthetic, or inaccurate.';
  const provider = data?.data?.provider;
  return (
    <div className="bp-panel bp-disclaimer" style={{ padding: 14 }}>
      <span className="bp-panel-title">Disclaimer</span>
      <div className="bp-divider" />
      <p style={{ fontSize: 11, lineHeight: 1.55, color: 'var(--bp-text-dim)', margin: 0 }}>
        {text}
      </p>
      {provider && (
        <div style={{ fontSize: 10, color: 'var(--bp-text-faint)', marginTop: 8, letterSpacing: '0.08em' }}>
          Source: {provider}
          {data?.data?.source && data.data.source !== provider ? ` (${data.data.source})` : ''}
        </div>
      )}
    </div>
  );
}
