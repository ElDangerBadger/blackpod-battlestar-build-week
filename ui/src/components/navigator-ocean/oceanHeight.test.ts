import { describe, expect, it } from "vitest";

import {
  oceanWaveHeight,
  sampleOceanSurface,
  volatilityIntensity,
} from "./oceanHeight";

describe("volatilityIntensity", () => {
  it("increases monotonically from glass to storm", () => {
    const order = ["glass", "gentle", "moderate", "high", "storm"] as const;
    for (let index = 1; index < order.length; index += 1) {
      expect(volatilityIntensity(order[index])).toBeGreaterThan(
        volatilityIntensity(order[index - 1]),
      );
    }
  });
});

describe("oceanWaveHeight", () => {
  it("is deterministic for identical inputs", () => {
    const first = oceanWaveHeight(0, 0, 12.34, 0.5, 0.1);
    const second = oceanWaveHeight(0, 0, 12.34, 0.5, 0.1);
    expect(first).toBe(second);
  });

  it("varies over time while motion is enabled", () => {
    const samples = [0, 1.5, 3].map((time) => oceanWaveHeight(0, 0, time, 0.6, 0));
    expect(new Set(samples).size).toBeGreaterThan(1);
  });

  it("is exactly flat at the full-chart anchor", () => {
    for (let time = 0; time < 40; time += 0.2) {
      expect(oceanWaveHeight(0, 0, time, 0.8, 1)).toBe(0);
    }
  });

  it("scales amplitude with volatility", () => {
    const swing = (volatility: number) => {
      let minimum = Infinity;
      let maximum = -Infinity;
      for (let time = 0; time < 40; time += 0.2) {
        const height = oceanWaveHeight(0, 0, time, volatility, 0);
        minimum = Math.min(minimum, height);
        maximum = Math.max(maximum, height);
      }
      return maximum - minimum;
    };
    expect(swing(0.9)).toBeGreaterThan(swing(0.1));
  });
});

describe("sampleOceanSurface", () => {
  it("returns height plus finite pitch and roll", () => {
    const sample = sampleOceanSurface(0, 0, 5, 0.7, 0);
    expect(Number.isFinite(sample.y)).toBe(true);
    expect(Number.isFinite(sample.pitch)).toBe(true);
    expect(Number.isFinite(sample.roll)).toBe(true);
  });

  it("matches the direct wave-height calculation", () => {
    const height = oceanWaveHeight(0, 0, 7.7, 0.5, 0.2);
    expect(sampleOceanSurface(0, 0, 7.7, 0.5, 0.2).y).toBe(height);
  });

  it("has no slope in the full chart", () => {
    expect(sampleOceanSurface(0, 0, 7.7, 0.5, 1)).toEqual({ y: 0, pitch: 0, roll: 0 });
  });
});
