import { render, screen } from "@testing-library/react";
import type { Html } from "@react-three/drei";
import type { ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ShipCallout from "./ShipCallout";
import type { NavigatorOceanMarketSummary } from "./types";

type HtmlProps = ComponentProps<typeof Html>;

const html = vi.hoisted(() => ({ render: vi.fn<(props: HtmlProps) => void>() }));

vi.mock("@react-three/drei", () => ({
  Html: (props: HtmlProps) => {
    html.render(props);
    return <div data-testid="ship-callout-anchor" style={props.style}>{props.children}</div>;
  },
}));

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

beforeEach(() => html.render.mockClear());

describe("ShipCallout presentation", () => {
  it("keeps CSS-pixel sizing at the existing world anchor without intercepting scene gestures", () => {
    const { rerender } = render(
      <ShipCallout summary={suppliedSummary} symbol="AAPL" currency="USD" zoomT={0} />,
    );
    for (const zoomT of [0, 0.08, 0.3, 0.55]) {
      rerender(<ShipCallout summary={suppliedSummary} symbol="AAPL" currency="USD" zoomT={zoomT} />);
      const props = html.render.mock.calls.at(-1)![0];
      expect(props.distanceFactor).toBeUndefined();
      expect(props.transform).toBeUndefined();
      expect(props.position).toEqual([-5.5, 2.5, 1.5]);
      expect(props.style?.pointerEvents).toBe("none");
    }
    expect(screen.getByText("333.74").closest(".bp-ship-callout")).toHaveAttribute("aria-hidden", "true");
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
    expect(html.render.mock.calls.at(-1)![0].style?.opacity).toBeCloseTo(opacity);
  });

  it.each([0.6001, 0.68, 1])("does not render the ship label in chartward view $0", (zoomT) => {
    const { container } = render(<ShipCallout summary={suppliedSummary} symbol="AAPL" zoomT={zoomT} />);
    expect(container).toBeEmptyDOMElement();
    expect(html.render).not.toHaveBeenCalled();
  });
});
