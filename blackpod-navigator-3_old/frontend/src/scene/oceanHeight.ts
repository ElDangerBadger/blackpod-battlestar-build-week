/**
 * Ocean wave height — CPU mirror of the GLSL vertex shader in `Ocean2.tsx`.
 *
 * ⚠️ KEEP IN SYNC: the formulas in `hash`, `noise`, and `oceanWaveHeight` below
 * must match the vertex shader exactly so the ship rides the *same* surface the
 * GPU renders. If you change the wave math in one place, change it in both.
 *
 * GLSL uses 32-bit floats while JS uses 64-bit doubles, so values are not
 * bit-identical, but they track the rendered surface closely enough that the
 * vessel visibly sits on the water and pitches/rolls with the swell.
 */
import type { Volatility } from '../types';

// Volatility → base wave intensity. Mirrors Ocean2's uVolatility mapping.
const VOL_INTENSITY: Record<Volatility, number> = {
  glass: 0.04,
  gentle: 0.15,
  moderate: 0.35,
  high: 0.65,
  storm: 1.0,
};

export function volatilityIntensity(v: Volatility): number {
  return VOL_INTENSITY[v] ?? 0.2;
}

// --- GLSL-equivalent value noise -----------------------------------------
function hash(x: number, y: number): number {
  const s = Math.sin(x * 127.1 + y * 311.7) * 43758.5453;
  return s - Math.floor(s); // fract
}

function noise(px: number, py: number): number {
  const ix = Math.floor(px);
  const iy = Math.floor(py);
  const fx = px - ix;
  const fy = py - iy;
  const a = hash(ix, iy);
  const b = hash(ix + 1, iy);
  const c = hash(ix, iy + 1);
  const d = hash(ix + 1, iy + 1);
  const ux = fx * fx * (3 - 2 * fx);
  const uy = fy * fy * (3 - 2 * fy);
  // mix(a,b,ux) + (c-a)*uy*(1-ux) + (d-b)*ux*uy
  return a + (b - a) * ux + (c - a) * uy * (1 - ux) + (d - b) * ux * uy;
}

/**
 * Wave displacement (in world units) at world position (x, z) and time.
 *
 * @param volUniform  the shader's uVolatility = volatilityIntensity * (1 - zoomT*0.92)
 * @param flatten     the shader's uFlatten = zoomT (0 = full waves, 1 = flat chart)
 */
export function oceanWaveHeight(
  x: number,
  z: number,
  time: number,
  volUniform: number,
  flatten: number,
): number {
  let wave = 0;
  wave += Math.sin(x * 0.05 + time * 0.6) * 0.6;
  wave += Math.sin(z * 0.04 + time * 0.5) * 0.5;
  wave += noise(x * 0.12 + time * 0.4, z * 0.12 + time * 0.4) * 1.2;
  wave += noise(x * 0.3 - time * 0.3, z * 0.3 - time * 0.3) * 0.6;
  const vol = volUniform * (1 - flatten);
  const amp = 0.05 + (1.6 - 0.05) * vol; // mix(0.05, 1.6, vol)
  return wave * amp;
}

export interface OceanSurfaceSample {
  /** wave height at the sampled point */
  y: number;
  /** rotation about X (bow up/down), radians */
  pitch: number;
  /** rotation about Z (side-to-side), radians */
  roll: number;
}

/**
 * Sample the surface height plus local slope (via finite differences) so a
 * floating object can both rise/fall and tilt to match the swell.
 */
export function sampleOceanSurface(
  x: number,
  z: number,
  time: number,
  volUniform: number,
  flatten: number,
  step = 1.4,
): OceanSurfaceSample {
  const y = oceanWaveHeight(x, z, time, volUniform, flatten);
  const hFwd = oceanWaveHeight(x, z + step, time, volUniform, flatten);
  const hBack = oceanWaveHeight(x, z - step, time, volUniform, flatten);
  const hRight = oceanWaveHeight(x + step, z, time, volUniform, flatten);
  const hLeft = oceanWaveHeight(x - step, z, time, volUniform, flatten);
  const pitch = Math.atan2(hFwd - hBack, 2 * step);
  const roll = Math.atan2(hRight - hLeft, 2 * step);
  return { y, pitch, roll };
}