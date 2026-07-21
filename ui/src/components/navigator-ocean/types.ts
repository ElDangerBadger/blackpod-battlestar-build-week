import type {
  NavigatorMarket,
  NavigatorMarketPoint,
} from "../../contracts/cabinContext";

/**
 * Read-only projection input. The shape remains structurally compatible with
 * the validated Navigator market contract consumed by the Captain's Cabin.
 */
export type NavigatorOceanMarketPoint = Readonly<NavigatorMarketPoint>;

export type NavigatorOceanMarket = Readonly<
  Omit<NavigatorMarket, "points"> & {
    points: readonly NavigatorOceanMarketPoint[];
  }
>;

export type NavigatorOceanVector = readonly [x: number, y: number, z: number];

export type NavigatorOceanProjectionOptions = Readonly<{
  /** Purely visual lateral exaggeration. It never changes source values. */
  oceanExaggeration?: number;
  visualHalfWidth?: number;
  visualDepth?: number;
  minDeviationFraction?: number;
  maxPoints?: number;
}>;

export type ProjectedNavigatorOcean = Readonly<{
  /** Sampled observations, ordered oldest to newest. */
  sampled: readonly NavigatorOceanMarketPoint[];
  /** Latest supplied close, used as the ship/world-origin anchor. */
  priceNow: number;
  /** Latest supplied moving average, or null when it was not supplied. */
  maNow: number | null;
  /** Historical close path; the final point is always at x=0 and z=0. */
  wakePoints: readonly NavigatorOceanVector[];
  /** Moving-average path aligned with sampled observations; gaps remain null. */
  maPoints: readonly (NavigatorOceanVector | null)[];
  /** One semantic color per wake point based only on supplied MA values. */
  wakeColors: readonly string[];
  stepZ: number;
  priceToWorld: number;
  zSpan: number;
  worldHalfWidth: number;
}>;

