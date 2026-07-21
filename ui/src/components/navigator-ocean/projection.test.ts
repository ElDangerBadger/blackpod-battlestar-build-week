import { describe, expect, it } from "vitest";

import type { NavigatorMarket } from "../../contracts/cabinContext";
import { projectNavigatorOcean } from "./projection";

function marketWithPoints(count: number): NavigatorMarket {
  const points = Array.from({ length: count }, (_, index) => ({
    t: index + 1,
    o: 98 + index,
    h: 102 + index,
    l: 97 + index,
    c: 100 + index,
    v: 1_000 + index,
    ma: index < 2 ? null : 99 + index,
    atr: 2,
  }));

  return {
    symbol: "AAPL",
    name: "Apple Inc.",
    category: "equity",
    timeframe: "1d",
    ma_period: 250,
    currency: "USD",
    points,
    summary: {
      last_price: count ? 99 + count : 0,
      last_ma: count > 2 ? 98 + count : null,
      pct_vs_ma: count > 2 ? 1 : 0,
      position: "above",
      trend_slope_pct: 1,
      volatility: "moderate",
      atr: 2,
      atr_pct: 2,
      ma_period: 250,
      bar_count: count,
    },
  };
}

describe("projectNavigatorOcean", () => {
  it("accepts the existing NavigatorMarket contract and produces stable ship-centered geometry", () => {
    const projection = projectNavigatorOcean(marketWithPoints(4), {
      visualHalfWidth: 30,
      visualDepth: 90,
      minDeviationFraction: 0.01,
    });

    expect(projection).not.toBeNull();
    expect(projection?.priceNow).toBe(103);
    expect(projection?.maNow).toBe(102);
    expect(projection?.wakePoints).toEqual([
      [-30, 0.22, -90],
      [-20, 0.22, -60],
      [-10, 0.22, -30],
      [0, 0.22, -0],
    ]);
    expect(projection?.maPoints).toEqual([
      null,
      null,
      [-20, 0.18, -30],
      [-10, 0.18, -0],
    ]);
    expect(projection?.wakeColors).toEqual([
      "#9ca3af",
      "#9ca3af",
      "#22c55e",
      "#22c55e",
    ]);
    expect(projection?.zSpan).toBe(90);
  });

  it("uses deterministic Math.ceil sampling, stays within maxPoints, and retains the final point", () => {
    const market = marketWithPoints(1_000);
    const projection = projectNavigatorOcean(market, { maxPoints: 500 });

    expect(projection?.sampled).toHaveLength(500);
    expect(projection?.sampled.slice(0, 4).map((point) => point.t)).toEqual([1, 3, 5, 7]);
    expect(projection?.sampled.at(-2)?.t).toBe(997);
    expect(projection?.sampled.at(-1)?.t).toBe(1_000);
    expect(projection?.wakePoints.at(-1)).toEqual([0, 0.22, -0]);
  });

  it("does not mutate its input", () => {
    const market = marketWithPoints(12);
    const before = structuredClone(market);
    Object.freeze(market.points);
    market.points.forEach(Object.freeze);

    projectNavigatorOcean(market, { maxPoints: 5 });

    expect(market).toEqual(before);
  });

  it("preserves missing moving-average evidence without substituting price", () => {
    const market = marketWithPoints(2);
    const projection = projectNavigatorOcean(market);

    expect(projection?.priceNow).toBe(101);
    expect(projection?.maNow).toBeNull();
    expect(projection?.maPoints).toEqual([null, null]);
    expect(projection?.wakeColors).toEqual(["#9ca3af", "#9ca3af"]);
  });

  it("returns null for an empty observation set and rejects unsafe projection options", () => {
    expect(projectNavigatorOcean(marketWithPoints(0))).toBeNull();
    expect(() => projectNavigatorOcean(marketWithPoints(2), { maxPoints: 0 })).toThrow(
      "maxPoints must be a positive integer",
    );
  });
});

