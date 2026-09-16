import { describe, expect, it, vi } from "vitest";

import type { NavigatorMarket } from "../contracts/cabinContext";
import type { NavigatorMarketVariant } from "../contracts/navigatorCatalog";
import { artifact, createMissionBundleFixture } from "../test/missionFixture";
import { createMissionViewModel } from "./viewModel";
import {
  chooseNavigatorCapture,
  hasNavigatorCapture,
  navigatorCaptureKey,
  navigatorCaptures,
  navigatorVariants,
  type NavigatorCaptureChoice,
  type NavigatorCaptureSelection,
} from "./navigatorSelection";

function market(symbol = "AAPL", timeframe: NavigatorMarket["timeframe"] = "1d", ma_period: NavigatorMarket["ma_period"] = 250): NavigatorMarket {
  return {
    symbol, name: `${symbol} recorded name`, category: "equity", timeframe, ma_period, currency: "USD",
    points: [
      { t: 100, o: 190, h: 192, l: 189, c: 191, v: 1_000, ma: null, atr: null },
      { t: 200, o: 191, h: 194, l: 190, c: 193, v: 1_200, ma: 188, atr: 3 },
    ],
    summary: {
      last_price: 193, last_ma: 188, pct_vs_ma: 2.6596, position: "above",
      trend_slope_pct: 0.5, volatility: "moderate", atr: 3, atr_pct: 1.5544,
      ma_period, bar_count: 2,
    },
    data: { provider: "yfinance", source: "provider", stale: true, age_seconds: 37 },
  };
}

function variant(symbol = "SPY", timeframe: NavigatorMarket["timeframe"] = "1d", ma_period: NavigatorMarket["ma_period"] = 250): NavigatorMarketVariant {
  return {
    market: market(symbol, timeframe, ma_period),
    capturedAt: "2026-09-16T14:00:00Z",
    sourceIdentity: "fleet-provider-capture",
    navigatorGitRevision: "b".repeat(40),
    reference: {
      ...artifact("navigator_fleet_market", `presentation/navigator_fleet/${symbol}-${timeframe}-ma${ma_period}.json`, "navigator.api.ohlc.v1"),
      producer: "navigator", observed_at: "2026-09-16T14:00:00Z",
    },
    navigatorSourceSha256: "c".repeat(64),
    navigatorWorktreeDirty: true,
  };
}

function fixture() {
  const mission = createMissionViewModel(createMissionBundleFixture());
  const original = market();
  const oldVariant = variant("AAPL", "1h", 20);
  oldVariant.sourceIdentity = "original-symbol-extra-capture";
  oldVariant.capturedAt = "2026-09-15T16:00:00Z";
  oldVariant.reference = {
    ...oldVariant.reference, name: "navigator_market_variant",
    path: "presentation/navigator_variants/1h-ma20.json", observed_at: oldVariant.capturedAt,
  };
  delete oldVariant.navigatorSourceSha256;
  delete oldVariant.navigatorWorktreeDirty;
  const fleetVariant = variant();
  fleetVariant.market.summary.last_price = 550.25;
  fleetVariant.market.points[1].c = 550.25;
  const reference = artifact("navigator_market", "presentation/navigator_market.json", "navigator.api.ohlc.v1");
  mission.market = {
    ...mission.market, status: "CAPTURED", navigatorMarket: original,
    capturedAt: "2026-09-14T12:00:00Z", sourceIdentity: "original-capture",
    artifactReference: reference, navigatorVariants: [oldVariant], navigatorFleetVariants: [fleetVariant],
  };
  return { mission, original, reference, oldVariant, fleetVariant };
}

describe("Navigator captured selection", () => {
  it("lists the original followed by both catalogs without copying market or reference objects", () => {
    const { mission, original, reference, oldVariant, fleetVariant } = fixture();
    const captures = navigatorCaptures(mission);
    expect(captures.map(({ market: data }) => navigatorCaptureKey(data))).toEqual(["AAPL:1d:250", "AAPL:1h:20", "SPY:1d:250"]);
    expect(captures.map(({ original: isOriginal }) => isOriginal)).toEqual([true, false, false]);
    expect(captures[0].market).toBe(original);
    expect(captures[0].reference).toBe(reference);
    expect(captures[1].market).toBe(oldVariant.market);
    expect(captures[1].reference).toBe(oldVariant.reference);
    expect(captures[2].market).toBe(fleetVariant.market);
    expect(captures[2].reference).toBe(fleetVariant.reference);
    expect(navigatorVariants(mission)[0]).toBe(oldVariant);
    expect(navigatorVariants(mission)[1]).toBe(fleetVariant);
  });

  it("keeps original, old-catalog, and fleet provenance separate without borrowing revisions", () => {
    const { mission } = fixture();
    const [original, oldVariant, fleetVariant] = navigatorCaptures(mission);
    expect(original).toMatchObject({ capturedAt: "2026-09-14T12:00:00Z", sourceIdentity: "original-capture", navigatorGitRevision: null, original: true });
    expect(original).not.toHaveProperty("navigatorSourceSha256");
    expect(oldVariant).toMatchObject({ capturedAt: "2026-09-15T16:00:00Z", sourceIdentity: "original-symbol-extra-capture", navigatorGitRevision: "b".repeat(40), original: false });
    expect(oldVariant).not.toHaveProperty("navigatorSourceSha256");
    expect(oldVariant).not.toHaveProperty("navigatorWorktreeDirty");
    expect(fleetVariant).toMatchObject({ capturedAt: "2026-09-16T14:00:00Z", sourceIdentity: "fleet-provider-capture", navigatorGitRevision: "b".repeat(40), navigatorSourceSha256: "c".repeat(64), navigatorWorktreeDirty: true, original: false });
    expect(original.market.summary.last_price).toBe(193);
    expect(fleetVariant.market.summary.last_price).toBe(550.25);
    expect(fleetVariant.market.data).toEqual({ provider: "yfinance", source: "provider", stale: true, age_seconds: 37 });
  });

  it("preserves explicitly clean source provenance", () => {
    const { mission, fleetVariant } = fixture();
    fleetVariant.navigatorWorktreeDirty = false;
    expect(navigatorCaptures(mission)[2].navigatorWorktreeDirty).toBe(false);
  });

  it("retains unknown original metadata as null", () => {
    const { mission } = fixture();
    mission.market.capturedAt = null;
    mission.market.sourceIdentity = null;
    delete mission.market.artifactReference;
    expect(navigatorCaptures(mission)[0]).toMatchObject({ capturedAt: null, sourceIdentity: null, reference: null, navigatorGitRevision: null });
  });

  it("selects without changing supplied prices, null averages, summaries, or mission state and without I/O", () => {
    const { mission, original } = fixture();
    const before = JSON.stringify(mission, (_key, value: unknown) => value instanceof Map ? [...value] : value);
    Object.freeze(original.summary);
    original.points.forEach(Object.freeze);
    Object.freeze(original.points);
    Object.freeze(original);
    const network = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("Unexpected capture fetch"));
    const clock = vi.spyOn(Date, "now").mockImplementation(() => { throw new Error("Unexpected current clock"); });
    try {
      const captures = navigatorCaptures(mission);
      expect(chooseNavigatorCapture(captures, "AAPL")!.market).toBe(original);
      expect(chooseNavigatorCapture(captures, "SPY")!.market.summary.last_price).toBe(550.25);
      expect(captures[0].market.points[0].ma).toBeNull();
      expect(JSON.stringify(mission, (_key, value: unknown) => value instanceof Map ? [...value] : value)).toBe(before);
      expect(network).not.toHaveBeenCalled();
      expect(clock).not.toHaveBeenCalled();
    } finally {
      clock.mockRestore();
      network.mockRestore();
    }
  });

  it("supports an original capture without either optional catalog", () => {
    const { mission, original } = fixture();
    delete mission.market.navigatorVariants;
    delete mission.market.navigatorFleetVariants;
    expect(navigatorVariants(mission)).toEqual([]);
    expect(navigatorCaptures(mission)).toHaveLength(1);
    expect(navigatorCaptures(mission)[0].market).toBe(original);
    expect(hasNavigatorCapture(mission, "AAPL")).toBe(true);
  });

  it("does not invent any capture when no market evidence exists", () => {
    const mission = createMissionViewModel(createMissionBundleFixture());
    expect(navigatorCaptures(mission)).toEqual([]);
    expect(navigatorVariants(mission)).toEqual([]);
    expect(chooseNavigatorCapture([], "AAPL")).toBeUndefined();
    expect(hasNavigatorCapture(mission, "AAPL")).toBe(false);
  });

  it("can enumerate supplied variants without an original but preserves the existing renderer availability guard", () => {
    const { mission, fleetVariant } = fixture();
    mission.market.navigatorMarket = null;
    const captures = navigatorCaptures(mission);
    expect(captures).toHaveLength(2);
    expect(captures.every((choice) => !choice.original)).toBe(true);
    expect(chooseNavigatorCapture(captures, "SPY")!.market).toBe(fleetVariant.market);
    expect(hasNavigatorCapture(mission, "SPY")).toBe(false);
    expect(hasNavigatorCapture(mission, "AAPL")).toBe(false);
  });

  it("preserves symbol availability across the original and both catalogs", () => {
    const { mission } = fixture();
    expect(hasNavigatorCapture(mission, "AAPL")).toBe(true);
    expect(hasNavigatorCapture(mission, "SPY")).toBe(true);
    expect(hasNavigatorCapture(mission, "MSFT")).toBe(false);
  });

  const choices = (): readonly NavigatorCaptureChoice[] => [
    { ...variant("AAPL", "1h", 20), original: true },
    { ...variant("SPY", "1wk", 20), original: false },
    { ...variant("SPY", "1h", 50), original: false },
    { ...variant("SPY", "1d", 250), original: false },
    { ...variant("SPY", "1h", 20), original: false },
  ];

  it.each<{ label: string; preferred: Pick<NavigatorCaptureSelection, "timeframe" | "ma_period"> | undefined; index: number; omitWeekly?: boolean }>([
    { label: "daily MA250 without a preference", preferred: undefined, index: 3 },
    { label: "the exact pair ahead of earlier same-interval captures", preferred: { timeframe: "1h", ma_period: 20 }, index: 4 },
    { label: "the first same-interval capture when that MA is absent", preferred: { timeframe: "1h", ma_period: 100 }, index: 2 },
    { label: "daily MA250 when the preferred interval is absent", preferred: { timeframe: "1wk", ma_period: 250 }, index: 3, omitWeekly: true },
  ])("chooses $label within the requested symbol", ({ preferred, index, omitWeekly }) => {
    const captures = choices();
    const available = omitWeekly ? captures.filter((choice) => choice.market.timeframe !== "1wk") : captures;
    expect(chooseNavigatorCapture(available, "SPY", preferred)).toBe(captures[index]);
  });

  it("uses the first supplied capture for that symbol when neither preference nor daily MA250 exists", () => {
    const captures = choices().filter((choice) => choice.market.timeframe !== "1d");
    expect(chooseNavigatorCapture(captures, "SPY", { timeframe: "1d", ma_period: 250 })).toBe(captures[1]);
    expect(chooseNavigatorCapture(captures, "SPY")).toBe(captures[1]);
  });

  it.each(["MSFT", "spy", "", " SPY "])("never substitutes another symbol for unavailable %j", (symbol) => {
    expect(chooseNavigatorCapture(choices(), symbol, { timeframe: "1h", ma_period: 20 })).toBeUndefined();
  });

  it("keys symbol, interval, and moving-average period independently", () => {
    expect(navigatorCaptureKey({ symbol: "SPY", timeframe: "1d", ma_period: 250 })).toBe("SPY:1d:250");
    expect(new Set([
      navigatorCaptureKey({ symbol: "SPY", timeframe: "1d", ma_period: 250 }),
      navigatorCaptureKey({ symbol: "AAPL", timeframe: "1d", ma_period: 250 }),
      navigatorCaptureKey({ symbol: "SPY", timeframe: "1h", ma_period: 250 }),
      navigatorCaptureKey({ symbol: "SPY", timeframe: "1d", ma_period: 20 }),
    ]).size).toBe(4);
  });
});
