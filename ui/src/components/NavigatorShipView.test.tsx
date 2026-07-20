import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  NavigatorShipView,
  type NavigatorShipData,
  type NavigatorShipDisplayContext,
} from "./NavigatorShipView";

const data: NavigatorShipData = {
  symbol: "AAPL",
  name: "Apple Inc.",
  category: "equity",
  timeframe: "1d",
  ma_period: 250,
  currency: "USD",
  regime: "RISK_ON",
  points: Array.from({ length: 12 }, (_, index) => ({
    t: Date.UTC(2026, 6, index + 1, 20) / 1000,
    o: 100 + index,
    h: 102 + index,
    l: 99 + index,
    c: 101 + index,
    v: 1_000_000 + index,
    ma: index < 2 ? null : 99 + index,
    atr: 2.5,
  })),
  summary: {
    last_price: 112,
    last_ma: 110,
    pct_vs_ma: 1.82,
    position: "above",
    trend_slope_pct: 0.34,
    volatility: "moderate",
    atr: 2.5,
    atr_pct: 2.23,
    ma_period: 250,
    bar_count: 12,
  },
  levels: {
    entry: 109,
    stop: null,
    target: 120,
    support: null,
    resistance: 118,
  },
};

const context: NavigatorShipDisplayContext = {
  presentationMode: "DEMO",
  runMode: "REPLAY",
  capturedAt: "2026-07-20T06:20:00Z",
  latestCompletedBar: "2026-07-12T20:00:00Z",
  marketStatus: null,
  exposure: {
    status: "NOT_CONFIGURED",
    symbol: "AAPL",
    direction: null,
    quantity: null,
    marketValue: null,
    allocationPercent: null,
    costBasis: null,
    unrealizedPnl: null,
    cash: null,
    equity: null,
    totalExposure: null,
    currency: null,
    capturedAt: null,
    mode: null,
    sourceIdentity: null,
  },
};

describe("NavigatorShipView", () => {
  it("renders supplied price, moving average, ship, levels, and honest missing-level states", () => {
    render(<NavigatorShipView data={data} context={context} variant="overview" />);

    expect(screen.getByRole("figure", { name: "Navigator ship view for AAPL" })).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("Apple Inc.")).toBeInTheDocument();
    expect(screen.getByText("DEMO")).toBeInTheDocument();
    expect(screen.getByText("REPLAY")).toBeInTheDocument();
    expect(screen.getByText(/Daily · 2026-07-01 — 2026-07-12/)).toBeInTheDocument();
    expect(screen.getByText(/Captured 2026-07-20 06:20Z/)).toBeInTheDocument();
    expect(screen.getByTestId("close-history-path")).toBeInTheDocument();
    expect(screen.getByTestId("moving-average-path")).toBeInTheDocument();
    expect(screen.getByTestId("current-price-ship")).toBeInTheDocument();
    expect(screen.getByTestId("level-entry")).toBeInTheDocument();
    expect(screen.getByTestId("level-target")).toBeInTheDocument();
    expect(screen.queryByTestId("level-stop")).not.toBeInTheDocument();
    expect(screen.getByText(/Stop, Support — Not present in mission artifact/)).toBeInTheDocument();
    expect(screen.getAllByText(/moderate/).length).toBeGreaterThan(0);
    expect(screen.getByText("RISK_ON")).toBeInTheDocument();
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
  });

  it("keeps overview mode read-only with no viewport controls", () => {
    render(<NavigatorShipView data={data} context={context} variant="overview" />);

    expect(screen.queryByRole("button", { name: "Zoom in" })).not.toBeInTheDocument();
    expect(screen.queryByRole("slider", { name: "History position" })).not.toBeInTheDocument();
  });

  it("provides semantic zoom, reset, wheel zoom, and history scrolling in interactive mode", () => {
    render(<NavigatorShipView data={data} context={context} variant="interactive" />);

    const zoomIn = screen.getByRole("button", { name: "Zoom in" });
    const reset = screen.getByRole("button", { name: "Reset chart view" });
    const chart = screen.getByRole("img", { name: /recorded price history with supplied 250-day moving average/ });
    expect(screen.getByText(/12 of 12 bars/)).toBeInTheDocument();

    fireEvent.click(zoomIn);
    expect(screen.getByText(/8 of 12 bars/)).toBeInTheDocument();
    expect(reset).toBeEnabled();

    const position = screen.getByRole("slider", { name: "History position" });
    expect(position).toBeEnabled();
    fireEvent.change(position, { target: { value: "0" } });
    expect(position).toHaveValue("0");

    fireEvent.wheel(chart, { deltaY: -100 });
    expect(screen.getByText(/of 12 bars/)).toBeInTheDocument();

    fireEvent.click(reset);
    expect(screen.getByText(/12 of 12 bars/)).toBeInTheDocument();
    expect(reset).toBeDisabled();
  });

  it("handles an empty observation set without inventing chart data", () => {
    render(<NavigatorShipView data={{ ...data, points: [] }} context={context} variant="interactive" />);

    expect(screen.getByText("No price observations present in mission artifact")).toBeInTheDocument();
    expect(screen.queryByTestId("close-history-path")).not.toBeInTheDocument();
    expect(screen.queryByTestId("current-price-ship")).not.toBeInTheDocument();
  });

  it("reports insufficient moving-average history without calculating a replacement", () => {
    const insufficient: NavigatorShipData = {
      ...data,
      points: data.points.slice(0, 10).map((point) => ({ ...point, ma: null })),
      summary: {
        ...data.summary,
        last_price: data.points[9]!.c,
        last_ma: null,
        pct_vs_ma: null,
        bar_count: 10,
      },
    };

    render(<NavigatorShipView data={insufficient} context={context} variant="interactive" />);

    expect(screen.queryByTestId("moving-average-path")).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: /250-day moving average is unavailable/ })).toBeInTheDocument();
    expect(screen.getByText(/10 recorded bars are insufficient/)).toBeInTheDocument();
    expect(screen.getByText(/does not calculate a replacement/)).toBeInTheDocument();
  });

  it("renders only exact captured active-symbol exposure and labels a missing source honestly", () => {
    const capturedContext: NavigatorShipDisplayContext = {
      ...context,
      exposure: {
        ...context.exposure,
        status: "POSITION",
        direction: "LONG",
        quantity: 12,
        marketValue: 4_004.88,
        allocationPercent: 7.25,
        cash: 9_000,
        equity: 55_240,
        totalExposure: 46_240,
        currency: "USD",
        capturedAt: "2026-07-20T06:20:00Z",
        mode: "FROZEN",
        sourceIdentity: "read-only-paper-ledger",
      },
    };
    const { rerender } = render(<NavigatorShipView data={data} context={capturedContext} variant="interactive" />);

    expect(screen.getByText("7.25% portfolio weight")).toBeInTheDocument();
    expect(screen.getByText("LONG")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("$4,004.88")).toBeInTheDocument();

    rerender(<NavigatorShipView data={data} context={context} variant="interactive" />);
    expect(screen.getByText(/no portfolio snapshot is configured/i)).toBeInTheDocument();
    expect(screen.getByText(/No zero exposure is inferred/i)).toBeInTheDocument();
    expect(screen.queryByText("0.00% portfolio weight")).not.toBeInTheDocument();
  });
});
