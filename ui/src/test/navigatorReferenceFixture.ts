import type { NavigatorReferenceFeed } from "../contracts/navigatorReference";

export const REFERENCE_NOW = "2026-09-18T15:00:00Z";
export const REFERENCE_PUBLICATION = "a".repeat(64);
export function navigatorReferenceFixture(): NavigatorReferenceFeed {
  const latest = Date.parse("2026-09-17T00:00:00Z") / 1000;
  return {
    schema_version: "blackpod.navigator_reference_feed.v1", status: "READY", checked_at: REFERENCE_NOW,
    message: "Verified current completed-bar reference.",
    snapshot: {
      schema_version: "navigator.reference_snapshot.v1", snapshot_id: "b".repeat(64),
      captured_at: "2026-09-18T14:59:00Z", provider_fetched_at: "2026-09-18T14:58:59Z",
      symbol: "AAPL", timeframe: "1d", ma_period: 250, bar_policy: "completed_regular_session",
      latest_bar_at: latest, expected_bar_at: latest, valid_until: "2026-09-18T20:00:00Z",
      calendar_id: `sentry-session-calendar-${"c".repeat(64)}`, provider: "yfinance", adjustment: "auto_adjust=True",
      market: {
        symbol: "AAPL", name: "Apple Inc.", category: "equity", timeframe: "1d", ma_period: 250, currency: "USD",
        points: [
          { t: latest - 86400, o: 320, h: 330, l: 319, c: 328, v: 10, ma: 290, atr: 4 },
          { t: latest, o: 328, h: 336, l: 325, c: 334, v: 20, ma: 291, atr: 4 },
        ],
        summary: { last_price: 334, last_ma: 291, pct_vs_ma: 14.78, position: "above", trend_slope_pct: 0.4,
          volatility: "gentle", atr: 4, atr_pct: 1.2, ma_period: 250, bar_count: 2 },
        data: { stale: false, age_seconds: 0, source: "provider", provider: "yfinance" },
      },
    },
  };
}
