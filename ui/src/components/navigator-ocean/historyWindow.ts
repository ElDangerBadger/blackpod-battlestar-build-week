import type { NavigatorOceanMarket, NavigatorOceanMarketPoint } from "./types";

export type HistoryPreset = "1M" | "3M" | "6M" | "1Y" | "all";

type HistoryPoint = Pick<NavigatorOceanMarketPoint, "t">;

const LOOKBACK_MONTHS: Record<Exclude<HistoryPreset, "all">, number> = {
  "1M": 1,
  "3M": 3,
  "6M": 6,
  "1Y": 12,
};

/** Keep the latest observation and at least two points when they are supplied. */
export function clampHistoryStart(points: readonly HistoryPoint[], index: number): number {
  const boundedIndex = Number.isFinite(index) ? Math.trunc(index) : 0;
  return Math.max(0, Math.min(Math.max(0, points.length - 2), boundedIndex));
}

/** UTC calendar lookback from captured evidence, never from the current clock. */
export function historyStartIndex(
  points: readonly HistoryPoint[],
  preset: HistoryPreset,
): number {
  if (preset === "all" || points.length < 2) return 0;

  const cutoff = new Date(points[points.length - 1].t * 1_000);
  const latestDay = cutoff.getUTCDate();
  // Move via the first of the month so March 31 minus one month cannot roll
  // forward into March. Preserve the captured UTC time of day throughout.
  cutoff.setUTCMonth(cutoff.getUTCMonth() - LOOKBACK_MONTHS[preset], 1);
  const monthEnd = new Date(cutoff.getTime());
  monthEnd.setUTCMonth(monthEnd.getUTCMonth() + 1, 0);
  cutoff.setUTCDate(Math.min(latestDay, monthEnd.getUTCDate()));

  const cutoffSeconds = cutoff.getTime() / 1_000;
  const index = points.findIndex((point) => point.t >= cutoffSeconds);
  return clampHistoryStart(points, index < 0 ? points.length - 1 : index);
}

/** Only the displayed observations change; all captured facts stay untouched. */
export function sliceHistory(
  market: NavigatorOceanMarket,
  startIndex: number,
): NavigatorOceanMarket {
  const start = clampHistoryStart(market.points, startIndex);
  return start === 0 ? market : { ...market, points: market.points.slice(start) };
}
