import { describe, expect, it } from "vitest";
import {
  CABIN_CONTEXT_SCHEMA,
  PORTFOLIO_SNAPSHOT_SCHEMA,
} from "../contracts/cabinContext";
import {
  parseCabinContext,
  parseNavigatorMarket,
  parsePortfolioSnapshot,
} from "./validateCabinContext";

const WHEN = "2026-07-19T18:30:00Z";
const HASH = "a".repeat(64);

function market() {
  return {
    symbol: "AAPL",
    name: "Apple Inc.",
    category: "equity",
    timeframe: "1d",
    ma_period: 250,
    currency: "USD",
    points: [
      { t: 100, o: 190, h: 192, l: 189, c: 191, v: 1000, ma: null, atr: null },
      { t: 200, o: 191, h: 194, l: 190, c: 193, v: 1200, ma: 188, atr: 3 },
    ],
    summary: {
      last_price: 193,
      last_ma: 188,
      pct_vs_ma: 2.6596,
      position: "above",
      trend_slope_pct: 0.5,
      volatility: "moderate",
      atr: 3,
      atr_pct: 1.5544,
      ma_period: 250,
      bar_count: 2,
    },
  };
}

function context() {
  return {
    schema_version: CABIN_CONTEXT_SCHEMA,
    mission_id: "mission-cabin-context-001",
    request_id: "request-cabin-context-001",
    symbol: "AAPL",
    run_mode: "LIVE",
    captured_at: WHEN,
    market_artifact: {
      name: "navigator_market",
      path: "presentation/navigator_market.json",
      sha256: HASH,
      producer: "navigator",
      byte_size: 10,
      schema_version: "navigator.api.ohlc.v1",
      observed_at: WHEN,
    },
    portfolio_artifact: null,
    capture_provenance: {
      market: {
        status: "CAPTURED",
        transport: "LOCAL_JSON",
        source_identity: "navigator-fixture-aapl",
        navigator_git_revision: "b".repeat(40),
      },
      portfolio: {
        status: "NOT_CONFIGURED",
        transport: null,
        source_identity: null,
      },
    },
  };
}

describe("Stage 4 presentation supplement contracts", () => {
  it("strictly validates the correlated cabin context", () => {
    const parsed = parseCabinContext(context(), {
      mission_id: "mission-cabin-context-001",
      request_id: "request-cabin-context-001",
      symbol: "AAPL",
      run_mode: "LIVE",
    });

    expect(parsed.market_artifact?.path).toBe("presentation/navigator_market.json");
    expect(() => parseCabinContext({ ...context(), symbol: "MSFT" }, {
      mission_id: "mission-cabin-context-001",
      request_id: "request-cabin-context-001",
      symbol: "AAPL",
      run_mode: "LIVE",
    })).toThrow(/conflicts with canonical mission correlation/);
    expect(() => parseCabinContext({ ...context(), extra: true })).toThrow(/unknown extra/);
  });

  it("validates Navigator points and recorded summary without deriving replacements", () => {
    const parsed = parseNavigatorMarket(market(), "AAPL");
    expect(parsed.summary.last_price).toBe(193);
    expect(parsed.points).toHaveLength(2);

    const inconsistent = market();
    inconsistent.summary.last_price = 999;
    expect(() => parseNavigatorMarket(inconsistent, "AAPL")).toThrow(/inconsistent/);

    const wrongSymbol = market();
    wrongSymbol.symbol = "MSFT";
    expect(() => parseNavigatorMarket(wrongSymbol, "AAPL")).toThrow(/does not match/);
  });

  it("rejects portfolio mutation fields and preserves valid read-only positions", () => {
    const value = {
      schema_version: PORTFOLIO_SNAPSHOT_SCHEMA,
      captured_at: WHEN,
      source_identity: "local-paper-ledger",
      mode: "LIVE",
      account_type: "PAPER",
      currency: "USD",
      cash: 8000,
      equity: 10000,
      total_exposure: 2000,
      positions: [{ symbol: "AAPL", quantity: 10, allocation_percent: 19.3 }],
    };
    expect(parsePortfolioSnapshot(value).positions[0]?.quantity).toBe(10);
    expect(() => parsePortfolioSnapshot({
      ...value,
      positions: [{ ...value.positions[0], broker_action: "SUBMIT_ORDER" }],
    })).toThrow(/unknown broker_action/);
  });
});
