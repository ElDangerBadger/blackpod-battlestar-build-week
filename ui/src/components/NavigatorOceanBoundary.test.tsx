import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { NavigatorMarket } from "../contracts/cabinContext";
import type { NavigatorMarketVariant } from "../contracts/navigatorCatalog";
import { NavigatorOceanBoundary } from "./NavigatorOceanBoundary";
import type { NavigatorOceanViewProps } from "./navigator-ocean/NavigatorOceanView";

function market(finalMa: number | null = 202.2): NavigatorMarket {
  return {
    symbol: "AAPL",
    name: "Apple Inc.",
    category: "equity",
    timeframe: "1d",
    ma_period: 250,
    currency: "USD",
    points: [
      { t: 1_752_796_800, o: 210, h: 214, l: 209, c: 213, v: 50_000_000, ma: 202, atr: 4 },
      { t: 1_752_883_200, o: 213, h: 216, l: 212, c: 215, v: 48_000_000, ma: finalMa, atr: 4.1 },
    ],
    summary: {
      last_price: 215,
      last_ma: finalMa,
      pct_vs_ma: finalMa === null ? 0 : 6.33,
      position: "above",
      trend_slope_pct: 1.2,
      volatility: "gentle",
      atr: 4.1,
      atr_pct: 1.91,
      ma_period: 250,
      bar_count: 2,
    },
  };
}

const baseProps = {
  presentationMode: "DEMO" as const,
  runMode: "REPLAY" as const,
  capturedAt: "2026-07-18T18:06:01Z",
  reducedMotion: false,
};

function capturedVariant(timeframe: NavigatorMarket["timeframe"], maPeriod: NavigatorMarket["ma_period"]): NavigatorMarketVariant {
  const data = market();
  data.timeframe = timeframe;
  data.ma_period = maPeriod;
  data.summary.ma_period = maPeriod;
  return {
    market: data,
    capturedAt: "2026-09-16T01:00:00Z",
    sourceIdentity: "navigator-canonical-capture",
    navigatorGitRevision: "a".repeat(40),
    reference: {
      name: "navigator_market_variant", path: `presentation/navigator_variants/${timeframe}-ma${maPeriod}.json`,
      sha256: "b".repeat(64), producer: "navigator", byte_size: 100,
      schema_version: "navigator.api.ohlc.v1", observed_at: "2026-09-16T01:00:00Z",
    },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("NavigatorOceanBoundary", () => {
  it("selects only supplied captured datasets without fetching or mutating the original", async () => {
    const original = market();
    const variant = capturedVariant("1h", 20);
    const before = JSON.stringify([original, variant]);
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const LazyStub = vi.fn((props: NavigatorOceanViewProps) => <p>Selected {props.data.timeframe} MA{props.data.ma_period} {props.capturedAt}</p>);
    render(<NavigatorOceanBoundary {...baseProps} data={original} variants={[variant]} capabilityProbe={() => true} loadView={async () => ({ default: LazyStub })} />);

    expect(await screen.findByText("Selected 1d MA250 2026-07-18T18:06:01Z")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Weekly" })).toBeDisabled();
    expect(screen.getByRole("option", { name: "MA20 bars" })).toBeDisabled();
    fireEvent.change(screen.getByRole("combobox", { name: "Captured bar interval" }), { target: { value: "1h" } });
    expect(await screen.findByText("Selected 1h MA20 2026-09-16T01:00:00Z")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Captured moving average" })).toHaveValue("20");
    expect(screen.getByText(/navigator-canonical-capture · not streaming/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Original mission capture" }));
    expect(await screen.findByText("Selected 1d MA250 2026-07-18T18:06:01Z")).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(JSON.stringify([original, variant])).toBe(before);
  });

  it("preserves selection metadata and MA changes in the WebGL-free SVG fallback", () => {
    const variant = capturedVariant("1d", 50);
    render(<NavigatorOceanBoundary {...baseProps} data={market()} variants={[variant]} capabilityProbe={() => false} />);
    fireEvent.change(screen.getByRole("combobox", { name: "Captured moving average" }), { target: { value: "50" } });
    expect(screen.getByRole("img", { name: /supplied 50-bar moving average/ })).toBeInTheDocument();
    expect(screen.getByText("Captured at: 2026-09-16T01:00:00Z")).toBeInTheDocument();
    expect(screen.getByText(/Navigator revision: a{40}/)).toBeInTheDocument();
  });

  it.each(["1h", "1wk"] as const)("labels the supplied MA in bars for a %s fallback capture", (timeframe) => {
    render(<NavigatorOceanBoundary {...baseProps} data={market()} variants={[capturedVariant(timeframe, 20)]} capabilityProbe={() => false} />);
    fireEvent.change(screen.getByRole("combobox", { name: "Captured bar interval" }), { target: { value: timeframe } });
    expect(screen.getByRole("img", { name: /supplied 20-bar moving average/ })).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /day moving average/ })).not.toBeInTheDocument();
    expect(screen.getByText("Captured at: 2026-09-16T01:00:00Z")).toBeInTheDocument();
  });

  it("announces a removed selection instead of silently retaining another capture's identity", () => {
    const original = market();
    const variant = capturedVariant("1d", 20);
    const probe = () => false;
    const { rerender } = render(<NavigatorOceanBoundary {...baseProps} data={original} variants={[variant]} capabilityProbe={probe} />);
    fireEvent.change(screen.getByRole("combobox", { name: "Captured moving average" }), { target: { value: "20" } });
    rerender(<NavigatorOceanBoundary {...baseProps} data={original} variants={[]} capabilityProbe={probe} />);
    expect(screen.getByText(/Selected capture is no longer available; showing the original/)).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Captured moving average" })).toHaveValue("250");
    expect(screen.getByText("Captured at: 2026-07-18T18:06:01Z")).toBeInTheDocument();
  });

  it("does not request the lazy module or network when WebGL is unavailable", () => {
    const loadView = vi.fn();
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);

    render(
      <NavigatorOceanBoundary
        {...baseProps}
        data={market()}
        capabilityProbe={() => false}
        loadView={loadView}
      />,
    );

    expect(screen.getByText(/3D ocean unavailable; canonical chart shown/i)).toBeInTheDocument();
    expect(screen.getByText(/Latest captured bar:/i)).toBeInTheDocument();
    expect(loadView).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("loads only after the expanded boundary is mounted and passes reduced motion unchanged", async () => {
    const LazyStub = vi.fn((props: NavigatorOceanViewProps) => (
      <p>Ocean loaded for {props.data.symbol}; reduced motion {String(props.reducedMotion)}</p>
    ));
    const loadView = vi.fn(async () => ({ default: LazyStub }));

    function Harness() {
      const [expanded, setExpanded] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setExpanded(true)}>Expand Navigator</button>
          {expanded ? (
            <NavigatorOceanBoundary
              {...baseProps}
              data={market()}
              reducedMotion
              capabilityProbe={() => true}
              loadView={loadView}
            />
          ) : null}
        </>
      );
    }

    render(<Harness />);
    expect(loadView).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Expand Navigator" }));
    expect(await screen.findByText("Ocean loaded for AAPL; reduced motion true")).toBeInTheDocument();
    expect(loadView).toHaveBeenCalledTimes(1);
    expect(LazyStub).toHaveBeenCalledWith(expect.objectContaining({ reducedMotion: true, data: market() }), undefined);
  });

  it("preserves the provider, stale cache status and disclaimer in the SVG fallback", () => {
    render(
      <NavigatorOceanBoundary
        {...baseProps}
        data={{
          ...market(),
          data: { stale: true, age_seconds: 120.5, source: "disk", provider: "yfinance" },
          disclaimer: "Educational visualization only. Data may be delayed.",
        }}
        capabilityProbe={() => false}
      />,
    );
    expect(screen.getByLabelText("Navigator market provenance")).toHaveTextContent("Provider: yfinance");
    expect(screen.getByLabelText("Navigator market provenance")).toHaveTextContent("STALE at capture");
    expect(screen.getByLabelText("Navigator market provenance")).toHaveTextContent("Source: disk");
    expect(screen.getByLabelText("Navigator market provenance")).toHaveTextContent("120.5s");
    expect(screen.getByText("Educational visualization only. Data may be delayed.")).toBeInTheDocument();
  });

  it("uses the SVG renderer for a valid single-observation history", () => {
    const loadView = vi.fn();
    const data = market();
    data.points = data.points.slice(0, 1);
    data.summary = {
      ...data.summary,
      last_price: data.points[0].c,
      last_ma: data.points[0].ma,
      bar_count: 1,
    };

    render(
      <NavigatorOceanBoundary
        {...baseProps}
        data={data}
        capabilityProbe={() => true}
        loadView={loadView}
      />,
    );

    expect(screen.getByText(/At least two supplied observations are required/i)).toBeInTheDocument();
    expect(screen.getByTestId("current-price-ship")).toBeInTheDocument();
    expect(loadView).not.toHaveBeenCalled();
  });

  it("preserves an unavailable final MA and never substitutes the latest price", () => {
    render(
      <NavigatorOceanBoundary
        {...baseProps}
        data={market(null)}
        capabilityProbe={() => false}
      />,
    );

    expect(screen.getByText(/Final supplied MA250: unavailable/i)).toBeInTheDocument();
    expect(screen.getAllByText("Not present").length).toBeGreaterThan(0);
    expect(screen.queryByText(/MA250.*\$215\.00/)).not.toBeInTheDocument();
  });

  it("falls back to the canonical SVG after a sanitized scene failure", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const Broken = () => { throw new Error("raw WebGL renderer details"); };

    render(
      <NavigatorOceanBoundary
        {...baseProps}
        data={market()}
        capabilityProbe={() => true}
        loadView={async () => ({ default: Broken })}
      />,
    );

    await waitFor(() => expect(screen.getByText(/3D ocean unavailable; canonical chart shown/i)).toBeInTheDocument());
    expect(screen.queryByText(/raw WebGL renderer details/i)).not.toBeInTheDocument();
  });

  it("contains no standalone store, API, fetch, mutation, approval, or execution seam", () => {
    const folder = join(dirname(fileURLToPath(import.meta.url)), "navigator-ocean");
    const source = readdirSync(folder)
      .filter((name) => /\.(ts|tsx)$/.test(name) && !name.endsWith(".test.ts") && !name.endsWith(".test.tsx"))
      .map((name) => readFileSync(join(folder, name), "utf8"))
      .join("\n");

    expect(source).not.toMatch(/from\s+["']zustand["']/);
    expect(source).not.toMatch(/lib\/api|useMarket|\bfetch\s*\(/);
    expect(source).not.toMatch(/SUBMIT_ORDER|CANCEL_ORDER|MODIFY_PORTFOLIO|BROKER_CALL/);
    // Captured interval/MA selection is now authorized; ticker management and
    // mutation/store/API seams remain prohibited.
    expect(source).not.toMatch(/APPROVE_HANDOFF|ticker selector/i);
  });
});
