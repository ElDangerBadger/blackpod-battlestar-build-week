import type { Ref } from "react";

import type { MarketContextViewModel } from "../data/viewModel";
import {
  NavigatorShipView,
  type NavigatorShipData,
  type NavigatorShipDisplayContext,
} from "./NavigatorShipView";

export function SentryAlerts({ warnings, onFocus }: { warnings: readonly string[]; onFocus: () => void }) {
  return (
    <button className="loose-paper sentry-copy" type="button" onClick={onFocus} aria-label="Focus mission warnings">
      <span className="paper-title">Mission warnings</span>
      {warnings.length ? warnings.slice(0, 3).map((warning) => (
        <span key={warning} title={warning}>{warningForDesk(warning)}</span>
      )) : <span>None recorded</span>}
    </button>
  );
}

function warningForDesk(warning: string): string {
  if (warning.startsWith("EXCLUDED_ORACLE_SNAPSHOT_SYMBOLS:")) {
    const symbols = warning.split(":", 2)[1]?.split(",").join(" · ") ?? "Not recorded";
    return `Excluded validation symbols: ${symbols}`;
  }
  if (warning === "MISSING_PRIOR_ORACLE_MEASUREMENTS") {
    return "Prior Oracle measurements unavailable";
  }
  return warning.replaceAll("_", " ").replaceAll(",", ", ");
}

export function MarketConditions({ symbol, market }: { symbol: string; market: MarketContextViewModel }) {
  return (
    <section className="loose-paper market-copy" aria-label="Supplemental Navigator market reference">
      <span className="paper-title">Navigator reference tape</span>
      {market.navigatorMarket ? (
        <dl>
          <div><dt>Asset</dt><dd>{symbol} · {market.companyName}</dd></div>
          <div><dt>Frame</dt><dd>{market.timeframe}</dd></div>
          <div><dt>Latest bar</dt><dd>{formatBarTime(market.latestCompletedBar)}</dd></div>
          <div><dt>Last</dt><dd>{formatPrice(market.navigatorMarket.summary.last_price, market.currency)}</dd></div>
          <div><dt>MA{market.navigatorMarket.ma_period}</dt><dd>{formatPrice(market.navigatorMarket.summary.last_ma, market.currency)}</dd></div>
          <div><dt>Sea</dt><dd>{market.navigatorMarket.summary.volatility}</dd></div>
        </dl>
      ) : <p>Security-specific market tape is not present in this mission artifact.</p>}
      <p className="market-source">Supplemental; not Oracle evidence. Market status: {market.marketStatus ?? "not recorded"}.</p>
    </section>
  );
}

export function MissionChart({
  missionId,
  snapshotCount,
  revision,
  shipData,
  shipContext,
  triggerRef,
  onOpenShip,
}: {
  missionId: string;
  snapshotCount: number;
  revision: number;
  shipData: NavigatorShipData | null;
  shipContext: NavigatorShipDisplayContext;
  triggerRef?: Ref<HTMLButtonElement>;
  onOpenShip: () => void;
}) {
  if (shipData) {
    return (
      <button ref={triggerRef} className="chart-copy navigator-chart-overview" type="button" onClick={onOpenShip} aria-label={`Open expanded Navigator ship view for ${shipData.symbol}`}>
        <span className="paper-title">Navigator reference chart · open</span>
        <NavigatorShipView data={shipData} context={shipContext} variant="overview" />
      </button>
    );
  }
  return (
    <section className="chart-copy" aria-label="Mission evidence chart">
      <span className="paper-title">Mission chart</span>
      <p>{missionId}</p>
      <div className="route-line" aria-hidden="true"><i /><i /><i /><i /><i /></div>
      <dl>
        <div><dt>Snapshots</dt><dd>{snapshotCount}</dd></div>
        <div><dt>Final revision</dt><dd>r{String(revision).padStart(4, "0")}</dd></div>
        <div><dt>Integrity</dt><dd>Hash-linked</dd></div>
      </dl>
    </section>
  );
}

function formatPrice(value: number | null, currency: string | null): string {
  if (value === null) return "Not present";
  if (!currency) return value.toFixed(2);
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: 2 }).format(value);
  } catch {
    return `${value.toFixed(2)} ${currency}`;
  }
}

function formatBarTime(value: string | null): string {
  if (!value) return "Not recorded";
  return value.slice(0, 10);
}

export function ShadowPlanPaper({ allowed, prohibited, outcome }: { allowed: readonly string[]; prohibited: readonly string[]; outcome: string }) {
  return (
    <section className="paper-order-copy" aria-label="Navigator SHADOW plan boundary">
      <span className="paper-title">Shadow plan</span>
      <strong>NO ORDER CREATED</strong>
      <dl>
        <div><dt>Outcome</dt><dd>{outcome}</dd></div>
        <div><dt>Mode</dt><dd>SHADOW</dd></div>
        <div><dt>Allowed</dt><dd>{allowed.join(" · ")}</dd></div>
      </dl>
      <p>Prohibited: {prohibited.join(" · ")}</p>
    </section>
  );
}
