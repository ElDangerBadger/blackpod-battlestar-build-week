import { describe, expect, it } from "vitest";

import { REPLAY_SEQUENCE, clampRevealCount, revealedStages } from "./sequence";

describe("mission replay sequence", () => {
  it("uses the canonical presentation order", () => {
    expect(REPLAY_SEQUENCE).toEqual([
      "HARBORMASTER",
      "ORACLE",
      "MODELDOCK",
      "COUNCIL",
      "GOVERNOR",
      "OPERATOR",
      "NAVIGATOR",
      "MISSION",
    ]);
  });

  it("clamps reveal state without changing canonical data", () => {
    expect(clampRevealCount(-3)).toBe(0);
    expect(clampRevealCount(99)).toBe(8);
    expect(revealedStages(3)).toEqual(["HARBORMASTER", "ORACLE", "MODELDOCK"]);
  });
});
