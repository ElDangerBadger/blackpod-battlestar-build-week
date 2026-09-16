import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { NavigatorOceanSceneProps } from "./NavigatorOceanScene";
import { NavigatorOceanView } from "./NavigatorOceanView";
import type { NavigatorOceanMarket } from "./types";

const scene = vi.hoisted(() => ({ render: vi.fn<(props: NavigatorOceanSceneProps) => void>() }));

vi.mock("./NavigatorOceanScene", () => ({
  NavigatorOceanScene: (props: NavigatorOceanSceneProps) => {
    scene.render(props);
    return <div data-testid="navigator-ocean-scene" />;
  },
}));

const baseProps = {
  presentationMode: "LIVE" as const,
  runMode: "LIVE" as const,
  capturedAt: "2026-09-15T20:05:00Z",
  reducedMotion: true,
};

function market(count = 800, finalMa: number | null = 264.82): NavigatorOceanMarket {
  const latestTime = Date.UTC(2026, 8, 15, 20) / 1000;
  const points = Array.from({ length: count }, (_, index) => {
    const c = index === count - 1 ? 333.74 : 100 + index * 0.25;
    return Object.freeze({
      t: latestTime - (count - 1 - index) * 86_400,
      o: c - 1, h: c + 2, l: c - 2, c, v: 1_000_000 + index,
      ma: index === count - 1 ? finalMa : index < 20 ? null : c - 2,
      atr: 4.1,
    });
  });
  return Object.freeze({
    symbol: "AAPL", name: "Apple Inc.", category: "equity", timeframe: "1d",
    ma_period: 250, currency: "USD", points: Object.freeze(points),
    summary: Object.freeze({
      last_price: 333.74, last_ma: finalMa, pct_vs_ma: finalMa === null ? 0 : 26.02,
      position: "above", trend_slope_pct: 0.9, volatility: "gentle",
      atr: 4.1, atr_pct: 1.2, ma_period: 250, bar_count: count,
    }),
    data: Object.freeze({ stale: false, age_seconds: 0, source: "provider", provider: "yfinance" }),
    disclaimer: "Captured reference only; not a streaming quote.",
  });
}

function currentScene(): NavigatorOceanSceneProps {
  expect(scene.render).toHaveBeenCalled();
  return scene.render.mock.calls.at(-1)![0];
}

function definition(label: string): HTMLElement {
  const facts = screen.getByLabelText("Canonical Navigator market facts");
  return within(facts).getByText(label, { selector: "dt" }).nextElementSibling as HTMLElement;
}

function date(value: number): string {
  return new Date(value * 1000).toISOString().slice(0, 10);
}

function expectCapturedFacts(source: NavigatorOceanMarket) {
  const latest = source.points.at(-1)!;
  expect(currentScene().projection.priceNow).toBe(latest.c);
  expect(currentScene().projection.maNow).toBe(latest.ma);
  expect(currentScene().projection.sampled.at(-1)).toBe(latest);
  expect(currentScene().data.summary).toEqual(source.summary);
  expect(definition("Displayed close")).toHaveTextContent("$333.74");
  expect(definition("Latest captured bar")).toHaveTextContent(new Date(latest.t * 1000).toISOString());
  expect(definition("Captured at")).toHaveTextContent(baseProps.capturedAt);
  expect(definition("Source history")).toHaveTextContent(date(source.points[0].t));
  expect(definition("Source history")).toHaveTextContent(date(latest.t));
}

beforeEach(() => scene.render.mockClear());
afterEach(() => vi.unstubAllGlobals());

describe("NavigatorOceanView local presentation controls", () => {
  it("starts with all supplied history and unit exaggeration while retaining canonical facts", () => {
    const source = market();
    render(<NavigatorOceanView {...baseProps} data={source} />);

    for (const name of ["1M", "3M", "6M", "1Y", "All history"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
    expect(screen.getByRole("slider", { name: "History start" })).toHaveValue("0");
    const exaggeration = screen.getByRole("slider", { name: "Ship price / MA exaggeration" });
    expect(exaggeration).toHaveAttribute("min", "0.2");
    expect(exaggeration).toHaveAttribute("max", "2.5");
    expect(exaggeration).toHaveValue("1");
    expect(definition("Visible history")).toHaveTextContent(date(source.points[0].t));
    expectCapturedFacts(source);
  });

  it.each(["1M", "3M", "6M", "1Y"])("%s limits only the visible trailing history, without fetching or altering source evidence", (preset) => {
    const source = market();
    const original = JSON.stringify(source);
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    render(<NavigatorOceanView {...baseProps} data={source} />);

    fireEvent.click(screen.getByRole("button", { name: preset }));

    const start = Number((screen.getByRole("slider", { name: "History start" }) as HTMLInputElement).value);
    expect(start).toBeGreaterThan(0);
    expect(start).toBeLessThan(source.points.length - 1);
    expect(currentScene().projection.sampled[0]).toBe(source.points[start]);
    expect(definition("Visible history")).toHaveTextContent(date(source.points[start].t));
    expectCapturedFacts(source);
    expect(JSON.stringify(source)).toBe(original);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("keeps presets ordered from shortest to longest and All history restores the original range", () => {
    const source = market();
    render(<NavigatorOceanView {...baseProps} data={source} />);
    let previousStart = source.points.length;
    for (const name of ["1M", "3M", "6M", "1Y", "All history"]) {
      fireEvent.click(screen.getByRole("button", { name }));
      const start = Number((screen.getByRole("slider", { name: "History start" }) as HTMLInputElement).value);
      expect(start).toBeLessThan(previousStart);
      expectCapturedFacts(source);
      previousStart = start;
    }
    expect(previousStart).toBe(0);
    expect(definition("Visible history")).toHaveTextContent(date(source.points[0].t));
  });

  it("moves the history start by source index while fixing the end at the latest captured bar", () => {
    const source = market();
    const original = JSON.stringify(source);
    render(<NavigatorOceanView {...baseProps} data={source} />);
    const start = screen.getByRole("slider", { name: "History start" });

    for (const index of [120, 600, 798]) {
      fireEvent.change(start, { target: { value: String(index) } });
      expect(start).toHaveValue(String(index));
      expect(currentScene().projection.sampled[0]).toBe(source.points[index]);
      expect(currentScene().projection.sampled.length).toBeGreaterThanOrEqual(2);
      expectCapturedFacts(source);
    }
    expect(JSON.stringify(source)).toBe(original);
  });

  it("passes exaggeration as presentation-only state without changing the normal chart projection", () => {
    const source = market();
    const original = JSON.stringify(source);
    render(<NavigatorOceanView {...baseProps} data={source} />);
    const baseline = currentScene().projection;
    const exaggeration = screen.getByRole("slider", { name: "Ship price / MA exaggeration" });

    for (const factor of [0.2, 2.5, 1]) {
      fireEvent.change(exaggeration, { target: { value: String(factor) } });
      const projection = currentScene().projection;
      expect(exaggeration).toHaveValue(String(factor));
      expect(currentScene().oceanExaggeration).toBe(factor);
      expect(projection).toEqual(baseline);
      expectCapturedFacts(source);
    }
    expect(JSON.stringify(source)).toBe(original);
  });

  it("does not manufacture a missing latest MA when selecting history or exaggeration", () => {
    const source = market(800, null);
    render(<NavigatorOceanView {...baseProps} data={source} />);

    fireEvent.click(screen.getByRole("button", { name: "1M" }));
    fireEvent.change(screen.getByRole("slider", { name: "Ship price / MA exaggeration" }), { target: { value: "2.5" } });

    expect(currentScene().projection.maNow).toBeNull();
    expect(currentScene().projection.maPoints.at(-1)).toBeNull();
    expect(definition("Supplied MA250")).toHaveTextContent("Unavailable in supplied artifact");
    expect(definition("Price vs MA")).toHaveTextContent("Unavailable — not inferred");
    expectCapturedFacts(source);
  });

  it("bounds presentation state to newly supplied shorter data without changing either artifact", () => {
    const first = market();
    const next = market(40);
    const originals = [JSON.stringify(first), JSON.stringify(next)];
    const { rerender } = render(<NavigatorOceanView {...baseProps} data={first} />);
    fireEvent.change(screen.getByRole("slider", { name: "History start" }), { target: { value: "798" } });

    rerender(<NavigatorOceanView {...baseProps} data={next} />);

    const start = Number((screen.getByRole("slider", { name: "History start" }) as HTMLInputElement).value);
    expect(start).toBeGreaterThanOrEqual(0);
    expect(start).toBeLessThan(next.points.length - 1);
    expect(currentScene().projection.sampled[0]).toBe(next.points[start]);
    expectCapturedFacts(next);
    expect([JSON.stringify(first), JSON.stringify(next)]).toEqual(originals);
  });

  it("shows and announces UTC hours/minutes when moving within hourly history", () => {
    const base = market(4);
    const source: NavigatorOceanMarket = {
      ...base, timeframe: "1h",
      points: base.points.map((point, index) => ({ ...point, t: Date.UTC(2026, 8, 15, 13 + index, 30) / 1000 })),
    };
    const original = JSON.stringify(source);
    render(<NavigatorOceanView {...baseProps} data={source} />);
    const slider = screen.getByRole("slider", { name: "History start" });
    expect(slider).toHaveAttribute("aria-valuetext", "2026-09-15 13:30 UTC");
    expect(slider.closest("label")).toHaveTextContent("From 2026-09-15 13:30 UTC");
    expect(slider.closest("label")).toHaveTextContent("to 2026-09-15 16:30 UTC");
    expect(definition("Source history")).toHaveTextContent("2026-09-15 13:30 UTC → 2026-09-15 16:30 UTC");

    fireEvent.change(slider, { target: { value: "1" } });
    expect(slider).toHaveAttribute("aria-valuetext", "2026-09-15 14:30 UTC");
    expect(slider.closest("label")).toHaveTextContent("From 2026-09-15 14:30 UTC");
    expect(definition("Visible history")).toHaveTextContent("2026-09-15 14:30 UTC → 2026-09-15 16:30 UTC");
    expect(definition("Source history")).toHaveTextContent("2026-09-15 13:30 UTC → 2026-09-15 16:30 UTC");
    expect(definition("Captured at")).toHaveTextContent(baseProps.capturedAt);
    expect(JSON.stringify(source)).toBe(original);
  });

  it.each(["1d", "1wk"] as const)("retains date-only history labels for %s captures", (timeframe) => {
    const source = { ...market(4), timeframe };
    render(<NavigatorOceanView {...baseProps} data={source} />);
    expect(screen.getByRole("slider", { name: "History start" })).toHaveAttribute("aria-valuetext", "2026-09-12");
    expect(definition("Source history").textContent).toBe("2026-09-12 → 2026-09-15");
    expect(definition("Visible history").textContent).toBe("2026-09-12 → 2026-09-15");
  });
});
