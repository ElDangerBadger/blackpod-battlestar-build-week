import { chartStretchX } from "./projection";
import type { LiveNavigatorPriceVisual, ProjectedNavigatorOcean } from "./types";

const LIVE_PRICE = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 6,
});

export function formatLiveTradePrice(price: number): string {
  return LIVE_PRICE.format(price);
}

/** Defense in depth: a late tick for another selection must never move this ship. */
export function matchingLivePrice(
  symbol: string,
  price: LiveNavigatorPriceVisual | null | undefined,
): LiveNavigatorPriceVisual | null {
  if (!price || price.symbol !== symbol || !Number.isFinite(price.price) || price.price <= 0
    || !Number.isFinite(Date.parse(price.tradeAt))
    || !["iex", "sip"].includes(price.feed)
    || !["LIVE", "STALE", "UNAVAILABLE", "WAITING", "CONNECTING"].includes(price.status)) return null;
  return price;
}

/**
 * The captured close remains the world origin. Only the separate ship/marker
 * moves on the price axis; no bar, MA, or time observation is added. Clip very
 * large displacement to keep an old capture's ship in view, with an explicit
 * readout notice. Numeric prices are never clipped or rewritten.
 */
export function projectLiveNavigatorPrice(
  symbol: string,
  projection: ProjectedNavigatorOcean,
  livePrice: LiveNavigatorPriceVisual | null | undefined,
  viewT: number,
): Readonly<{ trade: LiveNavigatorPriceVisual; x: number; rawX: number; clipped: boolean }> | null {
  const trade = matchingLivePrice(symbol, livePrice);
  if (!trade) return null;
  // Match the existing wake/MA/chart's quarter-step stretch exactly.
  const stretch = Math.round(chartStretchX(viewT) * 4) / 4;
  const rawX = (trade.price - projection.priceNow) * projection.priceToWorld * stretch;
  if (!Number.isFinite(rawX)) return null;
  const chartProgress = Math.max(0, Math.min(1, (viewT - 0.55) / 0.45));
  const limit = 6 + (Math.max(6, projection.worldHalfWidth * stretch) - 6) * chartProgress;
  const x = Math.max(-limit, Math.min(limit, rawX));
  return { trade, x, rawX, clipped: x !== rawX };
}
