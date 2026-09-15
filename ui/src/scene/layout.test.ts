import { describe, expect, it } from "vitest";

import {
  LOWER_CONTENT_REGIONS,
  NAVIGATION_REGIONS,
  SCENE_REGIONS,
  STAGE_CONTENT_REGIONS,
  STATUS_SLOTS,
  regionStyle,
  type SceneRegion,
} from "./layout";

function expectWithin(inner: SceneRegion, outer: SceneRegion) {
  expect(inner.left, `${inner.id} left page inset`).toBeGreaterThan(outer.left);
  expect(inner.top, `${inner.id} top page inset`).toBeGreaterThan(outer.top);
  expect(inner.left + inner.width, `${inner.id} right page inset`).toBeLessThan(outer.left + outer.width);
  expect(inner.top + inner.height, `${inner.id} bottom page inset`).toBeLessThan(outer.top + outer.height);
}

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

  it("keeps stage ink areas inset from their books and below the illustrated headings", () => {
    for (const [stage, content] of Object.entries(STAGE_CONTENT_REGIONS)) {
      const book = SCENE_REGIONS[`${stage}-book` as keyof typeof SCENE_REGIONS];
      expectWithin(content, book);
      // The illustrated titles occupy the upper portion of every stage book.
      expect(content.top - book.top, `${stage} heading clearance`).toBeGreaterThanOrEqual(6);
    }
  });

  it("keeps lower ink areas inside their illustrated pages and above the navigation", () => {
    for (const [name, content] of Object.entries(LOWER_CONTENT_REGIONS)) {
      const page = SCENE_REGIONS[name as keyof typeof LOWER_CONTENT_REGIONS];
      expectWithin(content, page);
      expect(content.left).toBeGreaterThanOrEqual(0);
      expect(content.left + content.width).toBeLessThanOrEqual(100);
      expect(content.top + content.height).toBeLessThan(SCENE_REGIONS["bottom-navigation"].top);
    }
  });

  it("separates the Navigator chart from the SHADOW paper and reserves the wax seal area", () => {
    const chart = LOWER_CONTENT_REGIONS["mission-chart"];
    const paper = LOWER_CONTENT_REGIONS["paper-order"];

    expect(chart.left + chart.width).toBeLessThan(SCENE_REGIONS["paper-order"].left);
    expect(chart.left + chart.width).toBeLessThan(paper.left);
    // The seal is near 86% scene height; keep a five-point ink-free buffer.
    const sealBottom = 86;
    const sealClearance = 5;
    expect(paper.top + paper.height).toBeLessThanOrEqual(sealBottom - sealClearance);
  });
});
