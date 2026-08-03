export default function HowToRead() {
  return (
    <div className="bp-panel" style={{ padding: 14 }}>
      <span className="bp-panel-title">How to Read</span>
      <div className="bp-divider" />
      <ol className="bp-howto">
        <li>The ship is the current price.</li>
        <li>The dashed yellow line is the moving average (bearing).</li>
        <li>Wake color shows where price has been: <span style={{ color: '#22c55e' }}>green</span> = above MA, <span style={{ color: '#9ca3af' }}>gray</span> = near, <span style={{ color: '#ef4444' }}>red</span> = below.</li>
        <li>Sea state = volatility. Calm glass to storm seas.</li>
        <li>Zoom (scroll) to change vantage. Top-down view reads as a chart.</li>
      </ol>
    </div>
  );
}