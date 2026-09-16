import { describe, expect, it } from "vitest";

import { formatLiveTradePrice, matchingLivePrice, projectLiveNavigatorPrice } from "./livePriceVisual";
import { chartStretchX } from "./projection";
import type { LiveNavigatorPriceVisual, ProjectedNavigatorOcean } from "./types";

const trade: LiveNavigatorPriceVisual = Object.freeze({
  symbol: "AAPL", price: 102, tradeAt: "2026-09-16T18:00:00.123Z", feed: "iex", status: "LIVE",
});
const projection: ProjectedNavigatorOcean = Object.freeze({
  sampled: [], priceNow: 100, maNow: 95, wakePoints: [], maPoints: [], wakeColors: [],
  stepZ: 4, priceToWorld: 0.5, zSpan: 100, worldHalfWidth: 38,
});

describe("separate live-price visual projection", () => {
  it("keeps fractional-cent trades visible instead of implying identical ticks", () => {
    expect(formatLiveTradePrice(102.001234)).toBe("102.001234");
    expect(formatLiveTradePrice(102)).toBe("102.00");
  });
  it.each([[102, 1], [98, -1], [100, 0]])("moves a trade at %s on the captured price axis only", (price, x) => {
    const result = projectLiveNavigatorPrice("AAPL", projection, { ...trade, price }, 0)!;
    expect(result.x).toBe(x);
    expect(result.rawX).toBe(x);
    expect(result.clipped).toBe(false);
    expect(result).not.toHaveProperty("y");
    expect(result).not.toHaveProperty("z");
  });

  it("applies normal chart-axis stretch without moving the captured close or MA", () => {
    const original = JSON.stringify(projection);
    const result = projectLiveNavigatorPrice("AAPL", projection, trade, 1)!;
    expect(result.x).toBe(14);
    expect(result.x).toBe((trade.price - projection.priceNow) * projection.priceToWorld * chartStretchX(1));
    expect(JSON.stringify(projection)).toBe(original);
    expect(result.trade).toBe(trade);
  });

  it("uses the caller's visual exaggeration but never modifies price values", () => {
    const result = projectLiveNavigatorPrice("AAPL", { ...projection, priceToWorld: 1.25 }, trade, 0)!;
    expect(result.x).toBe(2.5);
    expect(result.trade.price).toBe(102);
  });

  it("matches the saved chart's quantized price stretch during camera transition", () => {
    const viewT = 0.73;
    const result = projectLiveNavigatorPrice("AAPL", projection, trade, viewT)!;
    expect(result.rawX).toBe(Math.round(chartStretchX(viewT) * 4) / 4);
  });

  it.each([undefined, null])("keeps the legacy ship anchor when no live overlay exists", (missing) => {
    expect(projectLiveNavigatorPrice("AAPL", projection, missing, 0)).toBeNull();
  });

  it.each([NaN, Infinity, -Infinity, -1, 0])("rejects an invalid price %s", (price) => {
    expect(matchingLivePrice("AAPL", { ...trade, price })).toBeNull();
  });

  it("rejects cross-symbol ticks, invalid timestamps, unknown feeds, and unknown status", () => {
    expect(matchingLivePrice("SPY", trade)).toBeNull();
    expect(matchingLivePrice("AAPL", { ...trade, tradeAt: "not-a-time" })).toBeNull();
    expect(matchingLivePrice("AAPL", { ...trade, feed: "fake" as "iex" })).toBeNull();
    expect(matchingLivePrice("AAPL", { ...trade, status: "fake" as "LIVE" })).toBeNull();
  });

  it.each(["STALE", "WAITING", "CONNECTING", "UNAVAILABLE"] as const)("retains the last actual trade with %s status, not a fake tick", (status) => {
    const result = projectLiveNavigatorPrice("AAPL", projection, { ...trade, status }, 0)!;
    expect(result.trade.status).toBe(status);
    expect(result.trade.tradeAt).toBe(trade.tradeAt);
    expect(result.x).toBe(1);
  });

  it.each([10_000, 1])("clips large ship displacements while preserving the full price %s", (price) => {
    const result = projectLiveNavigatorPrice("AAPL", projection, { ...trade, price }, 0)!;
    expect(Math.abs(result.x)).toBe(6);
    expect(result.clipped).toBe(true);
    expect(result.trade.price).toBe(price);
    expect(result.rawX).toBe((price - 100) * 0.5);
  });

  it("bounds large chart displacement too, without extending the saved chart range", () => {
    const result = projectLiveNavigatorPrice("AAPL", projection, { ...trade, price: 10_000 }, 1)!;
    expect(result.x).toBeCloseTo(projection.worldHalfWidth * chartStretchX(1));
    expect(result.clipped).toBe(true);
    expect(projection.priceNow).toBe(100);
  });
});
