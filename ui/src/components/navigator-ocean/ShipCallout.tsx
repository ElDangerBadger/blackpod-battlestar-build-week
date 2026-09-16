import type { NavigatorOceanMarketSummary } from "./types";

export type ShipCalloutProps = Readonly<{
  summary: NavigatorOceanMarketSummary;
  symbol: string;
  zoomT: number;
  currency?: string;
}>;

const PRICE_INTEGER = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 0,
});
const PRICE_TWO_DECIMALS = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const PERCENT_TWO_DECIMALS = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  signDisplay: "always",
});

function formatPrice(value: number): string {
  return value >= 10_000
    ? PRICE_INTEGER.format(value)
    : PRICE_TWO_DECIMALS.format(value);
}

export function ShipCallout({
  summary,
  symbol,
  zoomT,
  currency,
}: ShipCalloutProps) {
  if (zoomT > 0.6) return null;

  const opacity = Math.max(0, 1 - Math.max(0, zoomT) / 0.6);
  const sentimentClass =
    summary.position === "above"
      ? "green"
      : summary.position === "below"
        ? "red"
        : "gray";
  const positionLabel =
    summary.position === "above"
      ? "Above MA"
      : summary.position === "below"
        ? "Below MA"
        : "Near MA";

  return (
    <div
      className="bp-ship-callout"
      aria-hidden="true"
      style={{ opacity, pointerEvents: "none" }}
    >
        <div className="lbl">
          {symbol} · PRICE (SHIP){currency ? ` · ${currency}` : ""}
        </div>
        <div className="price">{formatPrice(summary.last_price)}</div>
        <div className={`pct ${sentimentClass}`}>
          {PERCENT_TWO_DECIMALS.format(summary.pct_vs_ma)}%
        </div>
        <div className={`pos ${sentimentClass}`}>{positionLabel}</div>
    </div>
  );
}

export default ShipCallout;
