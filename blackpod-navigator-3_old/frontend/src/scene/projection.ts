/**
 * Shared coordinate projection for the ocean scene.
 *
 * Reference frame (price-anchored, ship-centered):
 *   - The ship occupies world-origin (0, 0, 0); it represents the *current* price.
 *   - +Z = into the screen (past). Each historical bar steps +stepZ.
 *   - Lateral X of any *value* v at bar i = (v - price_now) * priceToWorld * exag.
 *
 * Therefore:
 *   - Wake X at bar i  = (price[i] - price_now) * scale
 *   - MA line X at bar i = (ma[i]   - price_now) * scale
 *   - Ship is at X=0 (it IS price_now, the anchor).
 *
 * The visual gap between wake and MA line at any z is exactly (price[i] - ma[i])
 * — the price/trend divergence. The MA line is therefore a curving polyline whose
 * shape encodes the MA's own trajectory: rising MA bows left, falling MA bows right.
 */
import type { Bar } from '../types';

export interface ProjectionParams {
  bars: Bar[];
  oceanExag: number;       // user slider multiplier
  visualHalfWidth?: number; // target half-width in world units
  visualDepth?: number;     // target depth in world units
  minDeviationFraction?: number; // floor relative to price_now (to keep flat periods readable)
  maxBars?: number;
}

export interface ProjectedScene {
  /** Sampled bars (down to maxBars). Ordered as input (oldest → newest). */
  sampled: Bar[];
  /** price at the most recent bar — the world-origin anchor */
  priceNow: number;
  /** MA at the most recent bar (or priceNow if unavailable) */
  maNow: number;
  /** Wake polyline points [x, y, z]; index aligns with `sampled` (oldest → newest). */
  wakePoints: [number, number, number][];
  /** MA polyline points; null entries are for bars where MA isn't computable. */
  maPoints: ([number, number, number] | null)[];
  /** Hex color per wake vertex (segment color based on price[i] vs ma[i]). */
  wakeColors: string[];
  /** Z step between consecutive bars in world units. */
  stepZ: number;
  /** Price → world units scaling (lateral). */
  priceToWorld: number;
  /** Total Z span of the wake. */
  zSpan: number;
  /** Max lateral half-width actually used (for camera framing). */
  worldHalfWidth: number;
}

const DEFAULTS = {
  visualHalfWidth: 38,
  visualDepth: 1600,
  minDeviationFraction: 0.01,
  maxBars: 500,
};

/**
 * Lateral (price-axis) stretch applied as we approach the top-down chart vantage.
 *
 * Conventional charts use non-uniform axis scaling: a modest price range maps to
 * the full vertical canvas while a wide time range maps to the full horizontal.
 * Our world geometry is true-scale (great for the 3D ocean) but at top-down the
 * price axis (±~38 world units) is dwarfed by the time axis (~1600 units), giving
 * a near-flat line. This factor inflates the price (X) dimension so the chart
 * reads correctly. The underlying bar VALUES are unchanged — this is purely a
 * visual remap, exactly like a chart library choosing pixels-per-dollar.
 *
 *   viewT ≤ 0.55           → 1   (no stretch; cinematic ocean stays true-scale)
 *   viewT 0.55 → 1.0       → 1 → MAX (smoothstep)
 */
const CHART_STRETCH_MAX = 14;
export function chartStretchX(viewT: number): number {
  const k = Math.max(0, Math.min(1, (viewT - 0.55) / 0.45));
  const eased = k * k * (3 - 2 * k);
  return 1 + eased * (CHART_STRETCH_MAX - 1);
}

export function projectScene(params: ProjectionParams): ProjectedScene | null {
  const {
    bars,
    oceanExag,
    visualHalfWidth = DEFAULTS.visualHalfWidth,
    visualDepth = DEFAULTS.visualDepth,
    minDeviationFraction = DEFAULTS.minDeviationFraction,
    maxBars = DEFAULTS.maxBars,
  } = params;

  if (!bars.length) return null;

  // 1. Decimate to ≤ maxBars
  const n = bars.length;
  const stride = Math.max(1, Math.floor(n / maxBars));
  const sampled: Bar[] = [];
  for (let i = 0; i < n; i += stride) sampled.push(bars[i]);
  if (sampled[sampled.length - 1] !== bars[n - 1]) sampled.push(bars[n - 1]);

  const newest = sampled[sampled.length - 1];
  const priceNow = newest.c;
  const maNow = newest.ma ?? newest.c;

  // 2. Compute the lateral half-range we need to fit
  let maxRange = priceNow * minDeviationFraction; // floor so flat periods still read
  for (const b of sampled) {
    const dp = Math.abs(b.c - priceNow);
    if (dp > maxRange) maxRange = dp;
    if (b.ma != null) {
      const dm = Math.abs(b.ma - priceNow);
      if (dm > maxRange) maxRange = dm;
    }
  }

  const priceToWorld = (visualHalfWidth / maxRange) * oceanExag;

  // 3. Z step so wake spans visualDepth
  const total = sampled.length;
  const stepZ = visualDepth / Math.max(total - 1, 1);

  const wakePoints: [number, number, number][] = [];
  const maPoints: ([number, number, number] | null)[] = [];
  const wakeColors: string[] = [];

  for (let i = 0; i < total; i++) {
    const b = sampled[i];
    const ageIndex = total - 1 - i; // 0 at ship, increases toward horizon
    // Wake trails into NEGATIVE Z (behind the ship). Combined with the top-down
    // camera (up = +X), this makes the flattened chart read conventionally:
    // recent/ship on the RIGHT, oldest on the LEFT, higher price UP.
    const z = -ageIndex * stepZ;

    const wx = (b.c - priceNow) * priceToWorld;
    wakePoints.push([wx, 0.22, z]);

    if (b.ma != null) {
      const mx = (b.ma - priceNow) * priceToWorld;
      maPoints.push([mx, 0.18, z]);
      const diff = b.c - b.ma;
      const pct = (diff / b.ma) * 100;
      if (pct > 0.25) wakeColors.push('#22c55e');
      else if (pct < -0.25) wakeColors.push('#ef4444');
      else wakeColors.push('#9ca3af');
    } else {
      maPoints.push(null);
      wakeColors.push('#9ca3af');
    }
  }

  return {
    sampled,
    priceNow,
    maNow,
    wakePoints,
    maPoints,
    wakeColors,
    stepZ,
    priceToWorld,
    zSpan: (total - 1) * stepZ,
    worldHalfWidth: visualHalfWidth * oceanExag,
  };
}