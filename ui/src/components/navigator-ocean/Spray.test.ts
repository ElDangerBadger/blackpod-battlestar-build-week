import { describe, expect, it } from "vitest";

import { createSprayParticleSeeds } from "./Spray";

describe("createSprayParticleSeeds", () => {
  it("produces identical particle attributes for an identical seed", () => {
    const first = createSprayParticleSeeds(8, 12345);
    const second = createSprayParticleSeeds(8, 12345);
    expect(Array.from(first.seeds)).toEqual(Array.from(second.seeds));
    expect(Array.from(first.phases)).toEqual(Array.from(second.phases));
  });

  it("changes the attributes when the seed changes", () => {
    const first = createSprayParticleSeeds(8, 12345);
    const second = createSprayParticleSeeds(8, 54321);
    expect(Array.from(first.seeds)).not.toEqual(Array.from(second.seeds));
    expect(Array.from(first.phases)).not.toEqual(Array.from(second.phases));
  });

  it("keeps directions and phases in their canonical ranges", () => {
    const particles = createSprayParticleSeeds(32, 7);
    expect(particles.seeds).toHaveLength(96);
    expect(particles.phases).toHaveLength(32);
    for (let index = 0; index < 32; index += 1) {
      expect(particles.seeds[index * 3]).toBeGreaterThanOrEqual(-1);
      expect(particles.seeds[index * 3]).toBeLessThan(1);
      expect(particles.seeds[index * 3 + 1]).toBeGreaterThanOrEqual(0);
      expect(particles.seeds[index * 3 + 1]).toBeLessThan(1);
      expect(particles.seeds[index * 3 + 2]).toBeGreaterThanOrEqual(0);
      expect(particles.seeds[index * 3 + 2]).toBeLessThan(1);
      expect(particles.phases[index]).toBeGreaterThanOrEqual(0);
      expect(particles.phases[index]).toBeLessThan(1);
    }
  });

  it("rejects unsafe counts", () => {
    expect(() => createSprayParticleSeeds(-1)).toThrow("count must be a nonnegative integer");
    expect(() => createSprayParticleSeeds(1.5)).toThrow("count must be a nonnegative integer");
  });
});
