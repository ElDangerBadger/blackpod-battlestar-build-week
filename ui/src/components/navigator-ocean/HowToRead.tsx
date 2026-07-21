type HowToReadProps = Readonly<{
  maPeriod: number;
}>;

export function HowToRead({ maPeriod }: HowToReadProps) {
  return (
    <aside className="navigator-ocean__how-to" aria-label="How to read the Navigator ocean">
      <strong>How to read this sea chart</strong>
      <ul>
        <li><i className="legend-ship" aria-hidden="true" />Ship: latest captured close.</li>
        <li><i className="legend-wake" aria-hidden="true" />Wake: supplied price history.</li>
        <li><i className="legend-ma" aria-hidden="true" />Yellow bearing: supplied MA{maPeriod}.</li>
        <li><i className="legend-sea" aria-hidden="true" />Sea state: supplied volatility class.</li>
      </ul>
      <p>Wake color compares each supplied close with its supplied MA. It is presentation context, not a trade signal.</p>
    </aside>
  );
}
