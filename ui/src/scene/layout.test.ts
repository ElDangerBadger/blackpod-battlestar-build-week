import { describe, expect, it } from "vitest";

import {
  LOWER_CONTENT_REGIONS,
  NAVIGATION_REGIONS,
  SCENE_REGIONS,
  STAGE_CONTENT_REGIONS,
  STATUS_SLOTS,
  regionStyle,
} from "./layout";

describe("Captain's Cabin scene geometry", () => {
  it("keeps every overlay coordinate relative to the 4:3 scene", () => {
    const regions = [
      ...Object.values(SCENE_REGIONS),
      ...Object.values(STAGE_CONTENT_REGIONS),
      ...Object.values(LOWER_CONTENT_REGIONS),
      ...Object.values(STATUS_SLOTS),
      ...Object.values(NAVIGATION_REGIONS),
    ];

    expect(regions.length).toBeGreaterThan(0);
    for (const region of regions) {
      const style = regionStyle(region);
      for (const value of [style.left, style.top, style.width, style.height]) {
        expect(value, `${region.id} must stay percentage-positioned`).toMatch(/^-?\d+(?:\.\d+)?%$/);
        expect(value).not.toContain("px");
      }
    }
  });
});
