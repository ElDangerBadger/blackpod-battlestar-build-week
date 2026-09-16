import { describe, expect, it, vi } from "vitest";

import { clampHistoryStart, historyStartIndex, sliceHistory } from "./historyWindow";
import type { HistoryPreset } from "./historyWindow";
import type { NavigatorOceanMarket } from "./types";

function timestamps(...dates: string[]) {
  return dates.map((date) => ({ t: Date.parse(date) / 1_000 }));
}

function marketWithDates(...dates: string[]): NavigatorOceanMarket {
  return {
    symbol: "AAPL",
    name: "Apple Inc.",
    category: "equity",
    timeframe: "1d",
    ma_period: 250,
    currency: "USD",
    points: timestamps(...dates).map((point, index) => ({
      ...point,
      o: 99 + index,
      h: 102 + index,
      l: 98 + index,
      c: 100 + index,
      v: 1_000 + index,
      ma: index % 2 === 0 ? 90 + index : null,
      atr: index === 1 ? null : 2,
    })),
    summary: {
      last_price: 100 + dates.length - 1,
      last_ma: null,
      pct_vs_ma: 3.125,
      position: "above",
      trend_slope_pct: 1.375,
      volatility: "moderate",
      atr: 2.125,
      atr_pct: 2.25,
      ma_period: 250,
      bar_count: dates.length,
    },
    disclaimer: "Captured market reference.",
    data: { stale: false, age_seconds: 12, source: "provider", provider: "yfinance" },
  };
}

describe("historyStartIndex", () => {
  it.each<[HistoryPreset, string, string]>([
    ["1M", "2024-03-31T16:30:00Z", "2024-02-29T16:30:00Z"],
    ["1M", "2023-03-31T16:30:00Z", "2023-02-28T16:30:00Z"],
    ["3M", "2024-01-31T16:30:00Z", "2023-10-31T16:30:00Z"],
    ["6M", "2024-08-31T16:30:00Z", "2024-02-29T16:30:00Z"],
    ["1Y", "2024-02-29T16:30:00Z", "2023-02-28T16:30:00Z"],
  ])("applies %s as a month-end-clamped UTC calendar lookback", (preset, latest, cutoff) => {
    const cutoffSeconds = Date.parse(cutoff) / 1_000;
    const points = [
      { t: cutoffSeconds - 1 },
      { t: cutoffSeconds },
      { t: cutoffSeconds + 1 },
      { t: Date.parse(latest) / 1_000 },
    ];

    expect(historyStartIndex(points, preset)).toBe(1);
  });

  it("selects the first supplied observation after the cutoff when that date is missing", () => {
    const points = timestamps(
      "2024-08-14T20:00:00Z",
      "2024-08-16T20:00:00Z",
      "2024-08-19T20:00:00Z",
      "2024-09-15T20:00:00Z",
    );

    expect(historyStartIndex(points, "1M")).toBe(1);
  });

  it("uses UTC calendar dates even when the supplied instant has a different local date", () => {
    const points = timestamps(
      "2024-02-01T07:29:59Z",
      "2024-02-01T07:30:00Z",
      "2024-02-20T07:30:00Z",
      "2024-02-29T23:30:00-08:00",
    );

    expect(historyStartIndex(points, "1M")).toBe(1);
  });

  it("is independent of the current clock and deterministic for historical evidence", () => {
    const points = timestamps(
      "2020-01-01T00:00:00Z",
      "2020-02-01T00:00:00Z",
      "2020-02-20T00:00:00Z",
      "2020-03-01T00:00:00Z",
    );

    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date("2026-09-15T23:59:00Z"));
      expect(historyStartIndex(points, "1M")).toBe(1);
      vi.setSystemTime(new Date("2036-01-01T00:00:00Z"));
      expect(historyStartIndex(points, "1M")).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps two observations when only the latest observation falls within the window", () => {
    const points = timestamps(
      "2024-01-01T00:00:00Z",
      "2024-02-01T00:00:00Z",
      "2024-03-01T00:00:00Z",
      "2024-09-15T00:00:00Z",
    );

    expect(historyStartIndex(points, "1M")).toBe(2);
  });

  it("shows all supplied points for All or a lookback longer than available history", () => {
    const points = timestamps("2024-09-01T00:00:00Z", "2024-09-15T00:00:00Z");

    expect(historyStartIndex(points, "all")).toBe(0);
    expect(historyStartIndex(points, "1Y")).toBe(0);
    expect(historyStartIndex([], "1M")).toBe(0);
    expect(historyStartIndex(points.slice(0, 1), "1M")).toBe(0);
  });
});

describe("clampHistoryStart", () => {
  const points = [1, 2, 3, 4, 5].map((t) => ({ t }));

  it.each([
    [-5, 0],
    [0, 0],
    [1.9, 1],
    [3, 3],
    [4, 3],
    [100, 3],
    [Number.NaN, 0],
    [Number.POSITIVE_INFINITY, 0],
    [Number.NEGATIVE_INFINITY, 0],
  ])("clamps index %s to %s without dropping the latest two points", (index, expected) => {
    expect(clampHistoryStart(points, index)).toBe(expected);
  });

  it("handles empty, singleton, and two-point captures", () => {
    expect(clampHistoryStart([], 10)).toBe(0);
    expect(clampHistoryStart([{ t: 1 }], 10)).toBe(0);
    expect(clampHistoryStart([{ t: 1 }, { t: 2 }], 10)).toBe(0);
  });
});

describe("sliceHistory", () => {
  it("returns the original market for a full-history selection", () => {
    const market = marketWithDates("2024-01-01T00:00:00Z", "2024-02-01T00:00:00Z");

    expect(sliceHistory(market, 0)).toBe(market);
    expect(sliceHistory(market, -100)).toBe(market);
    expect(sliceHistory(market, Number.NaN)).toBe(market);
  });

  it("only slices points, retaining exact values, null MA gaps, and all captured metadata", () => {
    const market = marketWithDates(
      "2024-01-01T00:00:00Z",
      "2024-02-01T00:00:00Z",
      "2024-03-01T00:00:00Z",
      "2024-04-01T00:00:00Z",
    );
    const before = structuredClone(market);
    market.points.forEach(Object.freeze);
    Object.freeze(market.points);
    Object.freeze(market.summary);
    Object.freeze(market);

    const selected = sliceHistory(market, 1);

    expect(selected).not.toBe(market);
    expect(selected).toEqual({ ...market, points: market.points.slice(1) });
    expect(selected.summary).toBe(market.summary);
    expect(selected.data).toBe(market.data);
    expect(selected.timeframe).toBe("1d");
    expect(selected.ma_period).toBe(250);
    expect(selected.points[0]).toBe(market.points[1]);
    expect(selected.points[0].ma).toBeNull();
    expect(selected.points[0].atr).toBeNull();
    expect(selected.points[1].ma).toBe(92);
    expect(selected.points.at(-1)).toBe(market.points.at(-1));
    expect(market).toEqual(before);
  });

  it("clamps out-of-range starts while always retaining the latest supplied observation", () => {
    const market = marketWithDates(
      "2024-01-01T00:00:00Z",
      "2024-02-01T00:00:00Z",
      "2024-03-01T00:00:00Z",
    );

    const selected = sliceHistory(market, 100);

    expect(selected.points).toHaveLength(2);
    expect(selected.points).toEqual(market.points.slice(1));
    expect(selected.points.at(-1)).toBe(market.points.at(-1));
    expect(sliceHistory(marketWithDates(), 100).points).toEqual([]);
    const singleton = marketWithDates("2024-01-01T00:00:00Z");
    expect(sliceHistory(singleton, 100)).toBe(singleton);
  });
});
