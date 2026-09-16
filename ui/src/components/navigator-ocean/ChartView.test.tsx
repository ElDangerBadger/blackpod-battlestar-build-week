import { act, render, within } from "@testing-library/react";
import type { Html } from "@react-three/drei";
import type { ThreeEvent } from "@react-three/fiber";
import { createElement, type ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { NavigatorMarket } from "../../contracts/cabinContext";
import ChartView from "./ChartView";
import { chartStretchX, projectNavigatorOcean } from "./projection";

type HitPlaneProps = {
  onPointerMove: (event: ThreeEvent<PointerEvent>) => void;
  onPointerDown?: (event: ThreeEvent<PointerEvent>) => void;
  onPointerOut?: (event: ThreeEvent<PointerEvent>) => void;
};
type HtmlProps = ComponentProps<typeof Html>;

const scene = vi.hoisted(() => ({ hitPlane: null as HitPlaneProps | null }));

// Render only presentation HTML in jsdom; exercise the real component state
// with captured ThreeEvent handlers rather than requiring a WebGL context.
vi.mock("react/jsx-runtime", async (importOriginal) => {
  const runtime = await importOriginal<typeof import("react/jsx-runtime")>();
  const host = (factory: typeof runtime.jsx) => (
    type: Parameters<typeof runtime.jsx>[0],
    props: Parameters<typeof runtime.jsx>[1],
    key?: Parameters<typeof runtime.jsx>[2],
  ) => {
    const hostProps = (props ?? {}) as Record<string, unknown>;
    if (typeof type === "string" && ["group", "mesh", "planeGeometry", "circleGeometry", "meshBasicMaterial"].includes(type)) {
      if (type === "mesh" && typeof hostProps.onPointerMove === "function") scene.hitPlane = hostProps as unknown as HitPlaneProps;
      return factory("div", { children: hostProps.children, "data-scene-node": type }, key);
    }
    return factory(type, props, key);
  };
  return { ...runtime, jsx: host(runtime.jsx), jsxs: host(runtime.jsxs) };
});

vi.mock("react/jsx-dev-runtime", async (importOriginal) => {
  const runtime = await importOriginal<typeof import("react/jsx-dev-runtime")>();
  return {
    ...runtime,
    jsxDEV: (...args: Parameters<typeof runtime.jsxDEV>) => {
      const [type, props] = args;
      const hostProps = (props ?? {}) as Record<string, unknown>;
      if (typeof type === "string" && ["group", "mesh", "planeGeometry", "circleGeometry", "meshBasicMaterial"].includes(type)) {
        if (type === "mesh" && typeof hostProps.onPointerMove === "function") scene.hitPlane = hostProps as unknown as HitPlaneProps;
        args[0] = "div";
        args[1] = { children: hostProps.children, "data-scene-node": type };
      }
      return runtime.jsxDEV(...args);
    },
  };
});

vi.mock("@react-three/drei", () => ({
  Html: (props: HtmlProps) => createElement("div", {
    "data-testid": "chart-html",
    "data-position": JSON.stringify(props.position),
    style: props.style,
  }, props.children),
  Line: () => null,
}));

beforeEach(() => { scene.hitPlane = null; });

function sampleMarket(): NavigatorMarket {
  const values = [
    { t: Date.parse("2026-09-13T00:00:00Z") / 1000, c: 301.23, ma: null },
    { t: Date.parse("2026-09-14T00:00:00Z") / 1000, c: 320.56, ma: 315.45 },
    { t: Date.parse("2026-09-15T00:00:00Z") / 1000, c: 333.74, ma: 325.67 },
  ];
  return {
    symbol: "AAPL", name: "Apple Inc.", category: "equity", timeframe: "1d", ma_period: 250, currency: "USD",
    points: values.map((point) => ({ ...point, o: point.c, h: point.c + 1, l: point.c - 1, v: 1000, atr: 2 })),
    summary: {
      last_price: 333.74, last_ma: 325.67, pct_vs_ma: 2.48, position: "above",
      trend_slope_pct: 0.5, volatility: "gentle", atr: 2, atr_pct: 0.6, ma_period: 250, bar_count: 3,
    },
  };
}

function mountChart(viewT = 1, timeframe: NavigatorMarket["timeframe"] = "1d") {
  const market = sampleMarket();
  const before = JSON.stringify(market);
  market.points.forEach(Object.freeze);
  Object.freeze(market.points);
  Object.freeze(market.summary);
  Object.freeze(market);
  const projection = projectNavigatorOcean(market, { visualDepth: 200 })!;
  const rendered = render(
    <ChartView projection={projection} zoomT={1} viewT={viewT} maPeriod={250} timeframe={timeframe} />,
  );
  const stretch = Math.round(chartStretchX(viewT) * 4) / 4;
  const event = (x: number, z: number, buttons = 0) => ({
    point: { x, y: 0.2, z }, buttons, stopPropagation: vi.fn(),
  } as unknown as ThreeEvent<PointerEvent>);
  const pointer = (x: number, z: number, buttons = 0) => act(() => {
    expect(scene.hitPlane).not.toBeNull();
    scene.hitPlane!.onPointerMove(event(x, z, buttons));
  });
  return {
    ...rendered,
    projection,
    pointer,
    move(index: number, series: "price" | "ma" = "price", buttons = 0) {
      const point = series === "ma" ? projection.maPoints[index]! : projection.wakePoints[index];
      pointer(point[0] * stretch, point[2], buttons);
    },
    pointerDown() { act(() => scene.hitPlane!.onPointerDown!(event(0, 0, 1))); },
    pointerOut() { act(() => scene.hitPlane!.onPointerOut!(event(0, 0))); },
    tooltip() { return rendered.container.querySelector<HTMLElement>(".bp-hover-tip"); },
    row(label: string) {
      return within(this.tooltip()!).getByText(label).closest<HTMLElement>(".bp-hover-row")!;
    },
    expectUnchanged() { expect(JSON.stringify(market)).toBe(before); },
  };
}

describe("ChartView read-only chart interaction", () => {
  it("marks opposite price-label gutters and time labels without changing supplied observations", () => {
    const chart = mountChart();
    expect(chart.container.querySelectorAll(".bp-axis-label--right").length).toBeGreaterThan(0);
    expect(chart.container.querySelectorAll(".bp-axis-label--left").length).toBeGreaterThan(0);
    expect(chart.container.querySelectorAll(".bp-time-label").length).toBeGreaterThan(0);
    expect(chart.tooltip()).toBeNull();
    chart.expectUnchanged();
  });

  it("renders one time label per observation without repeated positions for a short history", () => {
    const chart = mountChart();
    const labels = [...chart.container.querySelectorAll(".bp-time-label")];
    const positions = labels.map((label) => label.closest("[data-position]")!.getAttribute("data-position"));

    expect(labels).toHaveLength(3);
    expect(new Set(positions).size).toBe(3);
    expect(positions.every((position) => position !== null)).toBe(true);
    for (const label of chart.container.querySelectorAll(".bp-axis-label")) {
      const position = JSON.parse(label.closest("[data-position]")!.getAttribute("data-position")!);
      expect(position[2]).toBeGreaterThanOrEqual(-(chart.projection.zSpan + chart.projection.zSpan * 0.025));
      expect(position[2]).toBeLessThanOrEqual(chart.projection.zSpan * 0.025);
    }
    chart.expectUnchanged();
  });

  it.each([1, 0.73])("selects exact price and MA observations using the rendered stretch at %s", (viewT) => {
    const chart = mountChart(viewT);
    chart.move(1, "price");
    expect(chart.tooltip()).toHaveAttribute("data-series", "price");
    expect(chart.row("Price")).toHaveClass("bp-hover-row--active");
    expect(chart.row("Price")).toHaveTextContent("320.56");
    expect(chart.row("MA(250)")).toHaveTextContent("315.45");
    expect(chart.row("MA(250)")).not.toHaveClass("bp-hover-row--active");

    chart.move(1, "ma");
    expect(chart.tooltip()).toHaveAttribute("data-series", "ma");
    expect(chart.row("MA(250)")).toHaveClass("bp-hover-row--active");
    expect(chart.row("Price")).not.toHaveClass("bp-hover-row--active");
    const position = JSON.parse(chart.tooltip()!.closest("[data-position]")!.getAttribute("data-position")!);
    const stretch = Math.round(chartStretchX(viewT) * 4) / 4;
    expect(position[0]).toBeCloseTo(chart.projection.maPoints[1]![0] * stretch);
    expect(position[2]).toBe(chart.projection.maPoints[1]![2]);
    chart.expectUnchanged();
  });

  it("updates the supplied date and prices when moving across timestamps", () => {
    const chart = mountChart();
    chart.move(1);
    expect(chart.tooltip()).toHaveTextContent("Sep 14, 2026");
    expect(chart.row("Price")).toHaveTextContent("320.56");
    chart.move(2);
    expect(chart.tooltip()).toHaveTextContent("Sep 15, 2026");
    expect(chart.row("Price")).toHaveTextContent("333.74");
    expect(chart.row("MA(250)")).toHaveTextContent("325.67");
  });

  it("retains missing MA as unavailable and does not invent a percentage", () => {
    const chart = mountChart();
    chart.move(0);
    expect(chart.tooltip()).toHaveAttribute("data-series", "price");
    expect(chart.row("Price")).toHaveTextContent("301.23");
    expect(chart.row("MA(250)")).toHaveTextContent("—");
    expect(within(chart.tooltip()!).queryByText("vs MA")).toBeNull();
    chart.expectUnchanged();
  });

  it("selects nearest supplied time observations and bounds indices at both ends", () => {
    const chart = mountChart();
    chart.pointer(0, -142);
    expect(chart.row("Price")).toHaveTextContent("320.56");
    chart.pointer(0, -153);
    expect(chart.row("Price")).toHaveTextContent("301.23");
    chart.pointer(0, -400);
    expect(chart.row("Price")).toHaveTextContent("301.23");
    chart.pointer(0, 100);
    expect(chart.row("Price")).toHaveTextContent("333.74");
  });

  it("clears the readout on pointer-down, drag motion, and leaving the chart", () => {
    const chart = mountChart();
    chart.move(1);
    expect(chart.tooltip()).not.toBeNull();
    chart.pointerDown();
    expect(chart.tooltip()).toBeNull();
    chart.move(1, "price", 1);
    expect(chart.tooltip()).toBeNull();
    chart.move(2);
    expect(chart.tooltip()).not.toBeNull();
    chart.move(2, "price", 2);
    expect(chart.tooltip()).toBeNull();
    chart.move(1);
    chart.pointerOut();
    expect(chart.tooltip()).toBeNull();
  });

  it("includes the UTC year and hour for intraday hover dates", () => {
    const chart = mountChart(1, "1h");
    chart.move(1);
    expect(chart.tooltip()).toHaveTextContent("Sep 14, 2026");
    expect(chart.tooltip()).toHaveTextContent("00:00 UTC");
  });
});
