import { describe, it, expect } from 'vitest';
import { projectScene, chartStretchX } from './projection';
import type { Bar } from '../types';

function bar(c: number, ma: number | null = null, i = 0): Bar {
  return {
    t: 1_700_000_000 + i * 86400,
    o: c,
    h: c + 1,
    l: c - 1,
    c,
    v: 1000,
    ma,
    atr: 1,
  };
}

function ramp(n: number, start = 100, step = 1, maOffset: number | null = 0): Bar[] {
  const out: Bar[] = [];
  for (let i = 0; i < n; i++) {
    const c = start + i * step;
    const ma = maOffset === null ? null : c - maOffset;
    out.push(bar(c, ma, i));
  }
  return out;
}

describe('chartStretchX', () => {
  it('is 1 below the chart threshold (cinematic ocean stays true-scale)', () => {
    expect(chartStretchX(0)).toBe(1);
    expect(chartStretchX(0.4)).toBe(1);
    expect(chartStretchX(0.55)).toBe(1);
  });

  it('increases monotonically from 0.55 to 1.0', () => {
    let prev = chartStretchX(0.55);
    for (let v = 0.6; v <= 1.0001; v += 0.05) {
      const cur = chartStretchX(v);
      expect(cur).toBeGreaterThanOrEqual(prev);
      prev = cur;
    }
  });

  it('reaches its max (>10x) at full chart zoom', () => {
    expect(chartStretchX(1)).toBeGreaterThan(10);
  });
});

describe('projectScene', () => {
  it('returns null for empty input', () => {
    expect(projectScene({ bars: [], oceanExag: 1 })).toBeNull();
  });

  it('anchors the ship at the world origin (current price, z=0)', () => {
    const p = projectScene({ bars: ramp(50), oceanExag: 1 })!;
    expect(p.priceNow).toBe(149); // start=100,step=1,n=50 → last close = 149
    const lastWake = p.wakePoints[p.wakePoints.length - 1];
    expect(lastWake[0]).toBeCloseTo(0, 6); // X = 0 at the ship
    expect(lastWake[2]).toBeCloseTo(0, 6); // Z = 0 at the ship
  });

  it('trails older bars into negative Z (conventional chart: oldest left)', () => {
    const p = projectScene({ bars: ramp(50), oceanExag: 1 })!;
    const firstWake = p.wakePoints[0]; // oldest bar
    expect(firstWake[2]).toBeLessThan(0);
  });

  it('maps prices above current to +X and below to -X', () => {
    // Rising ramp: every historical close < priceNow → all wake X should be <= 0.
    const p = projectScene({ bars: ramp(40), oceanExag: 1 })!;
    for (let i = 0; i < p.wakePoints.length - 1; i++) {
      expect(p.wakePoints[i][0]).toBeLessThanOrEqual(1e-9);
    }
    // Falling ramp: historical closes > priceNow → wake X should be >= 0.
    const pFall = projectScene({ bars: ramp(40, 200, -1), oceanExag: 1 })!;
    for (let i = 0; i < pFall.wakePoints.length - 1; i++) {
      expect(pFall.wakePoints[i][0]).toBeGreaterThanOrEqual(-1e-9);
    }
  });

  it('keeps MA gaps as null and fills MA points elsewhere', () => {
    const bars = ramp(30, 100, 1, 5);
    // Blank out MA on the first 10 bars (warmup period).
    for (let i = 0; i < 10; i++) bars[i].ma = null;
    const p = projectScene({ bars, oceanExag: 1 })!;
    expect(p.maPoints.slice(0, 10).every((x) => x === null)).toBe(true);
    expect(p.maPoints.slice(10).every((x) => x !== null)).toBe(true);
  });

  it('places the MA line laterally offset from the wake by (price-ma)*scale', () => {
    const bars = ramp(40, 100, 1, 4); // price is always 4 above its MA
    const p = projectScene({ bars, oceanExag: 1 })!;
    const i = 30;
    const wakeX = p.wakePoints[i][0];
    const maX = p.maPoints[i]![0];
    // wake - ma offset (in world units) should equal (price - ma) * priceToWorld
    const expected = (bars[i].c - bars[i].ma!) * p.priceToWorld;
    expect(wakeX - maX).toBeCloseTo(expected, 6);
  });

  it('decimates to <= maxBars', () => {
    const p = projectScene({ bars: ramp(5000), oceanExag: 1, maxBars: 500 })!;
    expect(p.sampled.length).toBeLessThanOrEqual(501); // +1 for forced last bar
    expect(p.wakePoints.length).toBe(p.sampled.length);
  });

  it('scales lateral spread with oceanExag', () => {
    const a = projectScene({ bars: ramp(50), oceanExag: 1 })!;
    const b = projectScene({ bars: ramp(50), oceanExag: 2 })!;
    expect(b.priceToWorld).toBeCloseTo(a.priceToWorld * 2, 6);
  });

  it('colors wake green above MA, red below, gray near', () => {
    const bars = [
      bar(110, 100, 0), // +10% → green
      bar(95, 100, 1),  // -5%  → red
      bar(100.1, 100, 2), // +0.1% → gray (within ±0.25%)
    ];
    const p = projectScene({ bars, oceanExag: 1 })!;
    expect(p.wakeColors[0]).toBe('#22c55e');
    expect(p.wakeColors[1]).toBe('#ef4444');
    expect(p.wakeColors[2]).toBe('#9ca3af');
  });
});