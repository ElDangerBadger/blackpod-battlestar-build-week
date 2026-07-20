import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { NavigatorShipView, type NavigatorShipData } from "./NavigatorShipView";

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

describe("NavigatorShipView", () => {
  it("renders supplied price, moving average, ship, levels, and honest missing-level states", () => {
    render(<NavigatorShipView data={data} variant="overview" />);

    expect(screen.getByRole("figure", { name: "Navigator ship view for AAPL" })).toBeInTheDocument();
    expect(screen.getByTestId("close-history-path")).toBeInTheDocument();
    expect(screen.getByTestId("moving-average-path")).toBeInTheDocument();
    expect(screen.getByTestId("current-price-ship")).toBeInTheDocument();
    expect(screen.getByTestId("level-entry")).toBeInTheDocument();
    expect(screen.getByTestId("level-target")).toBeInTheDocument();
    expect(screen.queryByTestId("level-stop")).not.toBeInTheDocument();
    expect(screen.getByText(/Stop, Support — Not present in mission artifact/)).toBeInTheDocument();
    expect(screen.getByText("moderate")).toBeInTheDocument();
    expect(screen.getByText(/Regime: RISK_ON/)).toBeInTheDocument();
  });

  it("keeps overview mode read-only with no viewport controls", () => {
    render(<NavigatorShipView data={data} variant="overview" />);

    expect(screen.queryByRole("button", { name: "Zoom in" })).not.toBeInTheDocument();
    expect(screen.queryByRole("slider", { name: "History position" })).not.toBeInTheDocument();
  });

  it("provides semantic zoom, reset, wheel zoom, and history scrolling in interactive mode", () => {
    render(<NavigatorShipView data={data} variant="interactive" />);

    const zoomIn = screen.getByRole("button", { name: "Zoom in" });
    const reset = screen.getByRole("button", { name: "Reset chart view" });
    const chart = screen.getByRole("img", { name: /price history with supplied 250-day moving average/ });
    expect(screen.getByText("12 of 12 bars")).toBeInTheDocument();

    fireEvent.click(zoomIn);
    expect(screen.getByText("8 of 12 bars")).toBeInTheDocument();
    expect(reset).toBeEnabled();

    const position = screen.getByRole("slider", { name: "History position" });
    expect(position).toBeEnabled();
    fireEvent.change(position, { target: { value: "0" } });
    expect(position).toHaveValue("0");

    fireEvent.wheel(chart, { deltaY: -100 });
    expect(screen.getByText(/of 12 bars/)).toBeInTheDocument();

    fireEvent.click(reset);
    expect(screen.getByText("12 of 12 bars")).toBeInTheDocument();
    expect(reset).toBeDisabled();
  });

  it("handles an empty observation set without inventing chart data", () => {
    render(<NavigatorShipView data={{ ...data, points: [] }} variant="interactive" />);

    expect(screen.getByText("No price observations present in mission artifact")).toBeInTheDocument();
    expect(screen.queryByTestId("close-history-path")).not.toBeInTheDocument();
    expect(screen.queryByTestId("current-price-ship")).not.toBeInTheDocument();
  });
});
