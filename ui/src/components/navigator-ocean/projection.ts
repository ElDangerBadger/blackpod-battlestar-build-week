import type {
  NavigatorOceanMarket,
  NavigatorOceanMarketPoint,
  NavigatorOceanProjectionOptions,
  NavigatorOceanVector,
  ProjectedNavigatorOcean,
} from "./types";

const DEFAULTS = {
  oceanExaggeration: 1,
  visualHalfWidth: 38,
  visualDepth: 1600,
  minDeviationFraction: 0.01,
  maxPoints: 500,
} as const;

const WAKE_COLOR = {
  above: "#22c55e",
  below: "#ef4444",
  nearOrUnavailable: "#9ca3af",
} as const;

function requirePositiveFinite(value: number, name: string): number {
  if (!Number.isFinite(value) || value <= 0) {
    throw new RangeError(`${name} must be a positive finite number`);
  }
  return value;
}

function requireMaxPoints(value: number): number {
  if (!Number.isInteger(value) || value < 1) {
    throw new RangeError("maxPoints must be a positive integer");
  }
  return value;
}

/**
 * Deterministically reduce a history without mutating it. The stride is based
 * on Math.ceil, the result never exceeds maxPoints, and the latest observation
 * is always retained even when it does not fall on the sampling stride.
 */
function sampleMarketPoints(
  points: readonly NavigatorOceanMarketPoint[],
  maxPoints: number,
): NavigatorOceanMarketPoint[] {
  if (points.length <= maxPoints) return points.slice();
  if (maxPoints === 1) return [points[points.length - 1]];

  const stride = Math.ceil(points.length / maxPoints);
  const sampled: NavigatorOceanMarketPoint[] = [];
  let finalSampledIndex = -1;

  for (let index = 0; index < points.length; index += stride) {
    sampled.push(points[index]);
    finalSampledIndex = index;
  }

  const finalPoint = points[points.length - 1];
  if (finalSampledIndex !== points.length - 1) {
    if (sampled.length === maxPoints) {
      sampled[sampled.length - 1] = finalPoint;
    } else {
      sampled.push(finalPoint);
    }
  }

  return sampled;
}

/**
 * Project validated Navigator market observations into ship-centered geometry.
 *
 * The latest close is the ship at world origin. Older observations trail into
 * negative Z. Moving-average gaps remain null; this layer never computes or
 * substitutes an MA value.
 */
export function projectNavigatorOcean(
  market: NavigatorOceanMarket,
  options: NavigatorOceanProjectionOptions = {},
): ProjectedNavigatorOcean | null {
  if (market.points.length === 0) return null;

  const oceanExaggeration = requirePositiveFinite(
    options.oceanExaggeration ?? DEFAULTS.oceanExaggeration,
    "oceanExaggeration",
  );
  const visualHalfWidth = requirePositiveFinite(
    options.visualHalfWidth ?? DEFAULTS.visualHalfWidth,
    "visualHalfWidth",
  );
  const visualDepth = requirePositiveFinite(
    options.visualDepth ?? DEFAULTS.visualDepth,
    "visualDepth",
  );
  const minDeviationFraction = requirePositiveFinite(
    options.minDeviationFraction ?? DEFAULTS.minDeviationFraction,
    "minDeviationFraction",
  );
  const maxPoints = requireMaxPoints(options.maxPoints ?? DEFAULTS.maxPoints);
  const sampled = sampleMarketPoints(market.points, maxPoints);
  const newest = sampled[sampled.length - 1];
  const priceNow = newest.c;
  const maNow = newest.ma;

  let maxRange = Math.max(
    Math.abs(priceNow) * minDeviationFraction,
    Number.EPSILON,
  );
  for (const point of sampled) {
    maxRange = Math.max(maxRange, Math.abs(point.c - priceNow));
    if (point.ma !== null) {
      maxRange = Math.max(maxRange, Math.abs(point.ma - priceNow));
    }
  }

  const priceToWorld = (visualHalfWidth / maxRange) * oceanExaggeration;
  const stepZ = visualDepth / Math.max(sampled.length - 1, 1);
  const wakePoints: NavigatorOceanVector[] = [];
  const maPoints: (NavigatorOceanVector | null)[] = [];
  const wakeColors: string[] = [];

  sampled.forEach((point, index) => {
    const ageIndex = sampled.length - 1 - index;
    const z = -ageIndex * stepZ;
    wakePoints.push([(point.c - priceNow) * priceToWorld, 0.22, z]);

    if (point.ma === null) {
      maPoints.push(null);
      wakeColors.push(WAKE_COLOR.nearOrUnavailable);
      return;
    }

    maPoints.push([(point.ma - priceNow) * priceToWorld, 0.18, z]);
    const percentFromMa = ((point.c - point.ma) / point.ma) * 100;
    if (percentFromMa > 0.25) wakeColors.push(WAKE_COLOR.above);
    else if (percentFromMa < -0.25) wakeColors.push(WAKE_COLOR.below);
    else wakeColors.push(WAKE_COLOR.nearOrUnavailable);
  });

  return {
    sampled,
    priceNow,
    maNow,
    wakePoints,
    maPoints,
    wakeColors,
    stepZ,
    priceToWorld,
    zSpan: (sampled.length - 1) * stepZ,
    worldHalfWidth: visualHalfWidth * oceanExaggeration,
  };
}

