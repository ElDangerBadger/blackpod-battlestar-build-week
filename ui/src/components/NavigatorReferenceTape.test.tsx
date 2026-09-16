import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CABIN_CONTEXT_SCHEMA, NAVIGATOR_MARKET_CONTRACT } from "../contracts/cabinContext";
import { createMissionViewModel } from "../data/viewModel";
import { artifact, createMissionBundleFixture } from "../test/missionFixture";
import { NavigatorReferenceTape } from "./NavigatorReferenceTape";

function capturedMission() {
  const bundle = createMissionBundleFixture();
  const reference = {
    ...artifact("navigator_market", "presentation/navigator_market.json", NAVIGATOR_MARKET_CONTRACT),
    producer: "navigator",
  };
  bundle.navigatorMarket = {
    symbol: "AAPL",
    name: "Apple Inc.",
    category: "equity",
    timeframe: "1d",
    ma_period: 250,
    currency: "USD",
    points: [
      { t: 1_752_796_800, o: 210, h: 214, l: 209, c: 213, v: 50_000_000, ma: 202, atr: 4 },
      { t: 1_752_883_200, o: 213, h: 216, l: 212, c: 215, v: 48_000_000, ma: 202.2, atr: 4.1 },
    ],
    summary: {
      last_price: 215, last_ma: 202.2, pct_vs_ma: 6.33, position: "above",
      trend_slope_pct: 1.2, volatility: "gentle", atr: 4.1, atr_pct: 1.91,
      ma_period: 250, bar_count: 2,
    },
    data: { provider: "yfinance", source: "provider", stale: false, age_seconds: 0 },
  };
  bundle.cabinContext = {
    schema_version: CABIN_CONTEXT_SCHEMA,
    mission_id: bundle.summary.mission_id,
    request_id: bundle.summary.request_id,
    symbol: "AAPL",
    run_mode: bundle.summary.run_mode,
    captured_at: "2026-07-18T18:06:41Z",
    market_artifact: reference,
    portfolio_artifact: null,
    capture_provenance: {
      market: { status: "CAPTURED", transport: "LOCAL_JSON", source_identity: "captured-navigator-reference", navigator_git_revision: "b".repeat(40) },
      portfolio: { status: "NOT_CONFIGURED", transport: null, source_identity: null },
    },
  };
  return bundle;
}

function fact(section: HTMLElement, label: string): HTMLElement {
  const term = within(section).getByText(label, { selector: "dt" });
  return term.nextElementSibling as HTMLElement;
}

describe("NavigatorReferenceTape", () => {
  it("presents captured prices, interval, moving average and timing without changing the evidence", () => {
    const bundle = capturedMission();
    const before = JSON.stringify({ market: bundle.navigatorMarket, context: bundle.cabinContext });
    render(<NavigatorReferenceTape mission={createMissionViewModel(bundle)} onOpenNavigator={vi.fn()} />);
    const prices = screen.getByRole("region", { name: "Price snapshot" });
    const timing = screen.getByRole("region", { name: "Capture timing" });

    expect(screen.getByText("AAPL · Apple Inc.")).toBeInTheDocument();
    expect(fact(prices, "Latest captured close")).toHaveTextContent("$215.00");
    expect(fact(prices, "Supplied MA250")).toHaveTextContent("$202.20");
    expect(fact(prices, "Recorded distance from MA250")).toHaveTextContent("+6.33%");
    expect(fact(prices, "Bar interval")).toHaveTextContent("Daily");
    expect(fact(prices, "Recorded sea state")).toHaveTextContent("gentle");
    expect(fact(timing, "Supplied observations")).toHaveTextContent("2");
    expect(fact(timing, "Capture time")).toHaveTextContent("Jul 18, 2026, 6:06:41 PM UTC");
    expect(screen.getByText(/Opening this module does not refresh either timestamp/)).toBeInTheDocument();
    expect(screen.getByText(/does not establish that a Navigator SHADOW plan exists/)).toBeInTheDocument();
    expect(JSON.stringify({ market: bundle.navigatorMarket, context: bundle.cabinContext })).toBe(before);
  });

  it("does not invent an average, relative position or percentage when no MA was supplied", () => {
    const bundle = capturedMission();
    bundle.navigatorMarket!.summary.last_ma = null;
    bundle.navigatorMarket!.summary.pct_vs_ma = 0;
    bundle.navigatorMarket!.points.forEach((point) => { point.ma = null; });
    render(<NavigatorReferenceTape mission={createMissionViewModel(bundle)} onOpenNavigator={vi.fn()} />);
    const prices = screen.getByRole("region", { name: "Price snapshot" });

    expect(fact(prices, "Supplied MA250")).toHaveTextContent("Not supplied");
    expect(fact(prices, "Price relative to MA250")).toHaveTextContent("Unavailable—no moving average was supplied");
    expect(fact(prices, "Recorded distance from MA250")).toHaveTextContent("Not supplied");
    expect(prices).not.toHaveTextContent("0.00%");
    expect(prices).not.toHaveTextContent("Above the moving average");
  });

  it("shows a meaningful empty state without substitutes or chart actions", () => {
    render(<NavigatorReferenceTape mission={createMissionViewModel(createMissionBundleFixture())} onOpenNavigator={vi.fn()} />);
    expect(screen.getByText("No captured market reference is attached to this mission.")).toBeInTheDocument();
    expect(screen.getByText(/No replacement values were created/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open full Navigator" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("labels provider metadata as capture-time provenance, not present quote freshness", () => {
    render(<NavigatorReferenceTape mission={createMissionViewModel(capturedMission())} onOpenNavigator={vi.fn()} />);
    const provenance = screen.getByLabelText("Navigator market provenance");
    expect(provenance).toHaveTextContent("Provider: yfinance · Source: provider · Not stale at capture");
    expect(provenance).toHaveTextContent("Provider cache age at capture: 0s. This is not a streaming quote.");
    expect(screen.getByText(/not a streaming quote, a holding, or a trade instruction/)).toBeInTheDocument();
    expect(screen.getByText("Capture source: captured-navigator-reference")).toBeInTheDocument();
  });

  it("preserves unknown capture provenance rather than supplying a current timestamp", () => {
    const bundle = capturedMission();
    bundle.cabinContext = null;
    delete bundle.navigatorMarket!.data;
    render(<NavigatorReferenceTape mission={createMissionViewModel(bundle)} onOpenNavigator={vi.fn()} />);
    const timing = screen.getByRole("region", { name: "Capture timing" });
    expect(fact(timing, "Capture time")).toHaveTextContent("Not recorded");
    expect(screen.getByLabelText("Navigator market provenance")).toHaveTextContent("Provider/cache provenance was not recorded in this capture");
    expect(screen.getByText("Capture source: Not recorded")).toBeInTheDocument();
  });

  it("links the validated original capture reference with a safe new-window target", () => {
    render(<NavigatorReferenceTape mission={createMissionViewModel(capturedMission())} onOpenNavigator={vi.fn()} />);
    const link = screen.getByRole("link", { name: "Open original Navigator market artifact" });
    expect(link).toHaveAttribute("href", "./demo/approved/presentation/navigator_market.json");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
  });

  it("does not construct an artifact link when the original capture reference is absent", () => {
    const bundle = capturedMission();
    bundle.cabinContext!.market_artifact = null;
    render(<NavigatorReferenceTape mission={createMissionViewModel(bundle)} onOpenNavigator={vi.fn()} />);
    expect(screen.queryByRole("link", { name: "Open original Navigator market artifact" })).not.toBeInTheDocument();
  });

  it.each([
    { path: "presentation/navigator_variants/1h-ma20.json" },
    { name: "unrelated_artifact" },
    { schema_version: "other.market.v1" },
  ])("does not label an unrelated reference as the original artifact: %j", (changedField) => {
    const bundle = capturedMission();
    Object.assign(bundle.cabinContext!.market_artifact!, changedField);
    render(<NavigatorReferenceTape mission={createMissionViewModel(bundle)} onOpenNavigator={vi.fn()} />);
    expect(screen.queryByRole("link", { name: "Open original Navigator market artifact" })).not.toBeInTheDocument();
  });

  it("opens full Navigator only when the user activates its presentation control", () => {
    const onOpenNavigator = vi.fn();
    const bundle = capturedMission();
    const before = JSON.stringify(bundle.navigatorMarket);
    render(<NavigatorReferenceTape mission={createMissionViewModel(bundle)} onOpenNavigator={onOpenNavigator} />);
    expect(onOpenNavigator).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Open full Navigator" }));
    expect(onOpenNavigator).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(bundle.navigatorMarket)).toBe(before);
  });
});
