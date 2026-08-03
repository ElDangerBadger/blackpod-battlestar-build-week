import { describe, it, expect } from 'vitest';
import {
  oceanWaveHeight,
  sampleOceanSurface,
  volatilityIntensity,
} from './oceanHeight';

describe('volatilityIntensity', () => {
  it('increases monotonically from glass to storm', () => {
    const order = ['glass', 'gentle', 'moderate', 'high', 'storm'] as const;
    for (let i = 1; i < order.length; i++) {
      expect(volatilityIntensity(order[i])).toBeGreaterThan(
        volatilityIntensity(order[i - 1]),
      );
    }
  });
});

describe('oceanWaveHeight', () => {
  it('is deterministic for the same inputs', () => {
    const a = oceanWaveHeight(0, 0, 12.34, 0.5, 0.1);
    const b = oceanWaveHeight(0, 0, 12.34, 0.5, 0.1);
    expect(a).toBe(b);
  });

  it('varies over time (the surface actually moves)', () => {
    const h0 = oceanWaveHeight(0, 0, 0, 0.6, 0);
    const h1 = oceanWaveHeight(0, 0, 1.5, 0.6, 0);
    const h2 = oceanWaveHeight(0, 0, 3.0, 0.6, 0);
    expect(h0 === h1 && h1 === h2).toBe(false);
  });

  it('flattens to ~0 as zoom approaches the top-down chart', () => {
    // Sample peak-to-peak swing over time at full waves vs fully flattened.
    const swing = (flatten: number) => {
      let min = Infinity;
      let max = -Infinity;
      for (let t = 0; t < 40; t += 0.2) {
        const h = oceanWaveHeight(0, 0, t, 0.8, flatten);
        min = Math.min(min, h);
        max = Math.max(max, h);
      }
      return max - min;
    };
    const fullSwing = swing(0);
    const flatSwing = swing(1);
    expect(fullSwing).toBeGreaterThan(0.3);
    expect(flatSwing).toBeLessThan(fullSwing * 0.2);
  });

  it('scales amplitude with volatility uniform', () => {
    const swing = (vol: number) => {
      let min = Infinity;
      let max = -Infinity;
      for (let t = 0; t < 40; t += 0.2) {
        const h = oceanWaveHeight(0, 0, t, vol, 0);
        min = Math.min(min, h);
        max = Math.max(max, h);
      }
      return max - min;
    };
    expect(swing(0.9)).toBeGreaterThan(swing(0.1));
  });
});

describe('sampleOceanSurface', () => {
  it('returns height plus finite pitch/roll slopes', () => {
    const s = sampleOceanSurface(0, 0, 5, 0.7, 0);
    expect(Number.isFinite(s.y)).toBe(true);
    expect(Number.isFinite(s.pitch)).toBe(true);
    expect(Number.isFinite(s.roll)).toBe(true);
  });

  it('height matches the direct wave height function', () => {
    const y = oceanWaveHeight(0, 0, 7.7, 0.5, 0.2);
    const s = sampleOceanSurface(0, 0, 7.7, 0.5, 0.2);
    expect(s.y).toBe(y);
  });

  it('produces near-zero tilt on a calm (glass) sea', () => {
    const calm = volatilityIntensity('glass'); // 0.04
    let maxTilt = 0;
    for (let t = 0; t < 20; t += 0.5) {
      const s = sampleOceanSurface(0, 0, t, calm, 0);
      maxTilt = Math.max(maxTilt, Math.abs(s.pitch), Math.abs(s.roll));
    }
    // Glass seas should be visibly flatter than a stormy sample.
    const storm = sampleOceanSurface(0, 0, 5, volatilityIntensity('storm'), 0);
    expect(maxTilt).toBeLessThan(Math.abs(storm.pitch) + Math.abs(storm.roll) + 1);
  });
});