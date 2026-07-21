import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { NavigatorMarket } from "../contracts/cabinContext";
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

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("NavigatorOceanBoundary", () => {
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
    expect(source).not.toMatch(/APPROVE_HANDOFF|ticker selector|timeframe selector|moving average selector/i);
  });
});
