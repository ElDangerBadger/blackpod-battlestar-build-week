import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import ShipCallout from "./ShipCallout";
import type { NavigatorOceanMarketSummary } from "./types";

const suppliedSummary: NavigatorOceanMarketSummary = Object.freeze({
  last_price: 333.74,
  last_ma: 264.82,
  pct_vs_ma: 26.02,
  position: "above",
  trend_slope_pct: 0.9,
  volatility: "gentle",
  atr: 4.1,
  atr_pct: 1.2,
  ma_period: 250,
  bar_count: 365,
});

describe("ShipCallout presentation", () => {
  it("keeps one screen-space readout without intercepting scene gestures", () => {
    const { rerender } = render(
      <ShipCallout summary={suppliedSummary} symbol="AAPL" currency="USD" zoomT={0} />,
    );
    for (const zoomT of [0, 0.08, 0.3, 0.55]) {
      rerender(<ShipCallout summary={suppliedSummary} symbol="AAPL" currency="USD" zoomT={zoomT} />);
      const callout = screen.getByText("333.74").closest(".bp-ship-callout") as HTMLElement;
      expect(callout.style.pointerEvents).toBe("none");
      expect(callout.style.transform).toBe("");
    }
    expect(screen.getByText("333.74").closest(".bp-ship-callout")).toHaveAttribute("aria-hidden", "true");
  });

  it("anchors the transparent 224px readout at bottom left with no world projection", () => {
    const css = readFileSync(resolve(__dirname, "navigator-ocean.css"), "utf8");
    const rule = css.match(/\.navigator-ocean \.bp-ship-callout \{([^}]+)\}/)![1];
    for (const declaration of ["position: absolute", "left: 12px", "bottom: 64px", "width: 224px", "background: transparent", "border: 0", "box-shadow: none"]) {
      expect(rule).toContain(declaration);
    }
    expect(rule).toContain("text-shadow:");
    const scene = readFileSync(resolve(__dirname, "NavigatorOceanScene.tsx"), "utf8");
    expect(scene.indexOf("<ShipCallout")).toBeGreaterThan(scene.indexOf("</Canvas>"));
    const callout = readFileSync(resolve(__dirname, "ShipCallout.tsx"), "utf8");
    expect(callout).not.toMatch(/calculatePosition|Vector3|<Html/);
  });

  it("formats only the supplied symbol, currency, price and percentage", () => {
    const before = JSON.stringify(suppliedSummary);
    render(<ShipCallout summary={suppliedSummary} symbol="AAPL" currency="EUR" zoomT={0.08} />);

    expect(screen.getByText("AAPL · PRICE (SHIP) · EUR")).toHaveClass("lbl");
    expect(screen.getByText("333.74")).toHaveClass("price");
    expect(screen.getByText("+26.02%")).toHaveClass("pct", "green");
    expect(screen.getByText("Above MA")).toHaveClass("pos", "green");
    expect(JSON.stringify(suppliedSummary)).toBe(before);
  });

  it.each([
    { position: "above", pct: 26.02, text: "+26.02%", label: "Above MA", color: "green" },
    { position: "below", pct: -4.25, text: "-4.25%", label: "Below MA", color: "red" },
    { position: "near", pct: 0, text: "+0.00%", label: "Near MA", color: "gray" },
  ] as const)("preserves the supplied $position position and color", ({ position, pct, text, label, color }) => {
    const summary = Object.freeze({ ...suppliedSummary, position, pct_vs_ma: pct });
    render(<ShipCallout summary={summary} symbol="SPY" zoomT={0} />);

    expect(screen.getByText("SPY · PRICE (SHIP)")).toHaveClass("lbl");
    expect(screen.getByText(text)).toHaveClass("pct", color);
    expect(screen.getByText(label)).toHaveClass("pos", color);
  });

  it.each([
    { zoomT: -1, opacity: 1 },
    { zoomT: 0, opacity: 1 },
    { zoomT: 0.3, opacity: 0.5 },
    { zoomT: 0.6, opacity: 0 },
  ])("preserves the original fade at zoom $zoomT", ({ zoomT, opacity }) => {
    render(<ShipCallout summary={suppliedSummary} symbol="AAPL" zoomT={zoomT} />);
    const callout = screen.getByText("333.74").closest(".bp-ship-callout") as HTMLElement;
    expect(Number(callout.style.opacity)).toBeCloseTo(opacity);
  });

  it.each([0.6001, 0.68, 1])("does not render the ship label in chartward view $0", (zoomT) => {
    const { container } = render(<ShipCallout summary={suppliedSummary} symbol="AAPL" zoomT={zoomT} />);
    expect(container).toBeEmptyDOMElement();
  });
});
