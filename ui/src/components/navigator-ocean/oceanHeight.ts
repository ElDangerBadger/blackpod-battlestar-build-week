import type { NavigatorOceanMarket } from "./types";

type Volatility = NavigatorOceanMarket["summary"]["volatility"];

const VOLATILITY_INTENSITY: Record<Volatility, number> = {
  glass: 0.04,
  gentle: 0.15,
  moderate: 0.35,
  high: 0.65,
  storm: 1,
};

export function volatilityIntensity(volatility: Volatility): number {
  return VOLATILITY_INTENSITY[volatility];
}

function hash(x: number, y: number): number {
  const sine = Math.sin(x * 127.1 + y * 311.7) * 43758.5453;
  return sine - Math.floor(sine);
}

function noise(x: number, y: number): number {
  const integerX = Math.floor(x);
  const integerY = Math.floor(y);
  const fractionX = x - integerX;
  const fractionY = y - integerY;
  const a = hash(integerX, integerY);
  const b = hash(integerX + 1, integerY);
  const c = hash(integerX, integerY + 1);
  const d = hash(integerX + 1, integerY + 1);
  const smoothX = fractionX * fractionX * (3 - 2 * fractionX);
  const smoothY = fractionY * fractionY * (3 - 2 * fractionY);
  return a
    + (b - a) * smoothX
    + (c - a) * smoothY * (1 - smoothX)
    + (d - b) * smoothX * smoothY;
}

function smoothstep(edge0: number, edge1: number, value: number): number {
  const progress = Math.max(0, Math.min(1, (value - edge0) / (edge1 - edge0)));
  return progress * progress * (3 - 2 * progress);
}

/**
 * CPU mirror of Ocean's vertex shader. The final chart-flatten multiplier is
 * deliberately shared with the shader so a full chart has exactly zero wave
 * displacement rather than V3's residual moving 0.05-amplitude surface.
 */
export function oceanWaveHeight(
  x: number,
  z: number,
  time: number,
  volatilityUniform: number,
  flatten: number,
): number {
  let wave = 0;
  wave += Math.sin(x * 0.05 + time * 0.6) * 0.6;
  wave += Math.sin(z * 0.04 + time * 0.5) * 0.5;
  wave += noise(x * 0.12 + time * 0.4, z * 0.12 + time * 0.4) * 1.2;
  wave += noise(x * 0.3 - time * 0.3, z * 0.3 - time * 0.3) * 0.6;

  const clampedFlatten = Math.max(0, Math.min(1, flatten));
  const volatility = volatilityUniform * (1 - clampedFlatten);
  const amplitude = 0.05 + (1.6 - 0.05) * volatility;
  const fullChartFade = 1 - smoothstep(0.92, 1, clampedFlatten);
  if (fullChartFade === 0) return 0;
  return wave * amplitude * fullChartFade;
}

export type OceanSurfaceSample = Readonly<{
  y: number;
  pitch: number;
  roll: number;
}>;

export function sampleOceanSurface(
  x: number,
  z: number,
  time: number,
  volatilityUniform: number,
  flatten: number,
  step = 1.4,
): OceanSurfaceSample {
  const y = oceanWaveHeight(x, z, time, volatilityUniform, flatten);
  const heightForward = oceanWaveHeight(x, z + step, time, volatilityUniform, flatten);
  const heightBack = oceanWaveHeight(x, z - step, time, volatilityUniform, flatten);
  const heightRight = oceanWaveHeight(x + step, z, time, volatilityUniform, flatten);
  const heightLeft = oceanWaveHeight(x - step, z, time, volatilityUniform, flatten);
  const pitch = Math.atan2(heightForward - heightBack, 2 * step);
  const roll = Math.atan2(heightRight - heightLeft, 2 * step);
  return { y, pitch, roll };
}
