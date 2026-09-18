import type { ReactNode } from "react";
import type { LiveNavigatorPriceVisual } from "./types";

type HowToReadProps = Readonly<{
  maPeriod: number;
  livePrice?: LiveNavigatorPriceVisual | null;
  children?: ReactNode;
}>;

export function HowToRead({ maPeriod, livePrice, children }: HowToReadProps) {
  return (
    <aside className="navigator-ocean__how-to" aria-label="How to read the Navigator ocean">
      <strong>How to read this sea chart</strong>
      <ul>
        <li><i className="legend-ship" aria-hidden="true" />Ship: {livePrice ? "last received Alpaca trade, separate from the captured close." : "latest captured close."}</li>
        <li><i className="legend-wake" aria-hidden="true" />Wake: supplied price history.</li>
        <li><i className="legend-ma" aria-hidden="true" />Yellow bearing: supplied MA{maPeriod}.</li>
        <li><i className="legend-sea" aria-hidden="true" />Sea state: supplied volatility class.</li>
      </ul>
      {livePrice ? <p>Cyan marker: separate last-trade overlay at the captured history edge, not a new bar. Live trades do not change the reference history, MA or sea state; current-reference refreshes are separate. {livePrice.feed === "iex" ? "IEX covers one exchange, not the consolidated market." : "SIP uses the consolidated market feed."} {livePrice.status !== "LIVE" ? "The last received trade is retained but stale; it is not a current quote." : "Prices change only when actual trades arrive."}</p> : null}
      <p>Wake color compares each supplied close with its supplied MA. It is presentation context, not a trade signal.</p>
      {children}
    </aside>
  );
}
