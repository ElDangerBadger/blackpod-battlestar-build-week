import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { NavigatorMarket } from "../contracts/cabinContext";
import type { NavigatorMarketVariant } from "../contracts/navigatorCatalog";
import { NavigatorOceanBoundary } from "./NavigatorOceanBoundary";
import type { NavigatorOceanViewProps } from "./navigator-ocean/NavigatorOceanView";

class Stream {
  static instances: Stream[] = [];
  onmessage: ((message: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();
  constructor(readonly url: string) { Stream.instances.push(this); }
  emit(symbol = "AAPL", price = 330.12) {
    const now = new Date().toISOString();
    this.onmessage?.({ data: JSON.stringify({ schema_version: "navigator.live_price.v1", symbol,
      provider: "alpaca", feed: "iex", status: "LIVE", price, trade_at: now, received_at: now,
      checked_at: now, message: "Read-only market data." }) } as MessageEvent);
  }
}
const id = "a".repeat(64);
const liveProps = { presentationMode: "LIVE" as const, runMode: "LIVE" as const, capturedAt: "2026-09-15T20:00:00Z", reducedMotion: true, livePublicationId: id };
const market = (symbol = "AAPL", timeframe: NavigatorMarket["timeframe"] = "1d", ma_period: NavigatorMarket["ma_period"] = 250): NavigatorMarket => ({
  symbol, name: symbol, category: "equity", timeframe, ma_period, currency: "USD",
  points: [{ t: 1_752_796_800, o: 210, h: 214, l: 209, c: 213, v: 500, ma: 202, atr: 4 },
    { t: 1_752_883_200, o: 213, h: 216, l: 212, c: 215, v: 480, ma: 202.2, atr: 4.1 }],
  summary: { last_price: 215, last_ma: 202.2, pct_vs_ma: 6.33, position: "above", trend_slope_pct: 1.2,
    volatility: "gentle", atr: 4.1, atr_pct: 1.91, ma_period, bar_count: 2 },
});
const capture = (data: NavigatorMarket): NavigatorMarketVariant => ({ market: data,
  capturedAt: "2026-09-16T01:00:00Z", sourceIdentity: "captured-fleet", navigatorGitRevision: "b".repeat(40),
  reference: { name: "navigator_fleet_market", path: `presentation/navigator_fleet/${data.symbol}/${data.timeframe}-ma${data.ma_period}.json`,
    sha256: "c".repeat(64), producer: "navigator", byte_size: 100, schema_version: "navigator.api.ohlc.v1", observed_at: "2026-09-16T01:00:00Z" },
});
const last = () => Stream.instances.at(-1)!;

describe("Navigator ephemeral live-price presentation", () => {
  beforeEach(() => {
    Stream.instances = [];
    vi.stubGlobal("EventSource", Stream);
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  });
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it.each([
    { presentationMode: "DEMO" as const }, { runMode: "REPLAY" as const }, { livePublicationId: null },
  ])("never subscribes or changes the offline renderer with %j", (changes) => {
    render(<NavigatorOceanBoundary {...liveProps} {...changes} data={market()} capabilityProbe={() => false} />);
    expect(Stream.instances).toHaveLength(0);
    expect(screen.queryByLabelText("Live Navigator market data")).not.toBeInTheDocument();
  });

  it("shows separate feed, timing and stale status alongside an unchanged captured SVG", () => {
    const data = market();
    const before = JSON.stringify(data);
    render(<NavigatorOceanBoundary {...liveProps} data={data} capabilityProbe={() => false} />);
    const fallback = screen.getByLabelText("Navigator canonical chart fallback");
    const svg = fallback.querySelector("svg")!.outerHTML;
    act(() => last().emit());
    const panel = screen.getByLabelText("Live Navigator market data");
    expect(within(panel).getByLabelText("Last received live trade")).toHaveTextContent("$330.12");
    expect(panel).toHaveTextContent("IEX: limited-exchange coverage");
    expect(panel).toHaveTextContent("Trade:");
    expect(panel).toHaveTextContent("captured history and MA remain fixed");
    act(() => last().onerror?.());
    expect(panel).toHaveTextContent("disconnected or unavailable");
    expect(panel).toHaveTextContent("Any retained price is not current");
    expect(fallback.querySelector("svg")!.outerHTML).toBe(svg);
    expect(JSON.stringify(data)).toBe(before);
  });

  it("passes exact selected captured pairs plus only the matching ephemeral quote to the scene", async () => {
    const original = market();
    const daily = capture(market("SPY"));
    const hourly = capture(market("SPY", "1h", 20));
    const inputs = JSON.stringify([original, daily, hourly]);
    const View = vi.fn((props: NavigatorOceanViewProps) => <p>Scene {props.data.symbol} {props.data.timeframe} MA{props.data.ma_period} · {props.livePrice?.price ?? "captured"}</p>);
    render(<NavigatorOceanBoundary {...liveProps} data={original} variants={[daily, hourly]} initialSymbol="SPY"
      initialCapture={{ symbol: "SPY", timeframe: "1h", ma_period: 20 }} capabilityProbe={() => true} loadView={async () => ({ default: View })} />);
    expect(await screen.findByText("Scene SPY 1h MA20 · captured")).toBeInTheDocument();
    expect(last().url).toMatch(/\/SPY$/);
    act(() => last().emit("SPY", 660.12));
    expect(screen.getByText("Scene SPY 1h MA20 · 660.12")).toBeInTheDocument();
    expect(View.mock.calls.at(-1)![0].data).toBe(hourly.market);
    const firstSource = last();
    fireEvent.change(screen.getByRole("combobox", { name: "Captured bar interval" }), { target: { value: "1d" } });
    expect(View.mock.calls.at(-1)![0].data).toBe(daily.market);
    expect(last()).toBe(firstSource);
    expect(firstSource.close).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("combobox", { name: "Navigator review symbol" }), { target: { value: "AAPL" } });
    expect(firstSource.close).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Scene AAPL 1d MA250 · captured")).toBeInTheDocument();
    expect(last().url).toMatch(/\/AAPL$/);
    expect(JSON.stringify([original, daily, hourly])).toBe(inputs);
  });

  it("offers pause/resume and captured reference without mutating or resetting the selected pair", async () => {
    const hourly = capture(market("SPY", "1h", 20));
    const View = vi.fn((props: NavigatorOceanViewProps) => <p>Price source {props.livePrice ? `${props.livePrice.price} ${props.livePrice.status}` : "captured"}</p>);
    const { unmount } = render(<NavigatorOceanBoundary {...liveProps} data={market()} variants={[hourly]} initialSymbol="SPY"
      capabilityProbe={() => true} loadView={async () => ({ default: View })} />);
    await screen.findByText("Price source captured");
    act(() => last().emit("SPY", 660.12));
    fireEvent.click(screen.getByRole("button", { name: "Pause live updates" }));
    expect(last().close).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Price source 660.12 UNAVAILABLE")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Resume live updates" }));
    expect(Stream.instances).toHaveLength(2);
    expect(screen.getByText("Price source 660.12 CONNECTING")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Captured reference" }));
    expect(last().close).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Price source captured")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Captured bar interval" })).toHaveValue("1h");
    expect(screen.getByRole("combobox", { name: "Captured moving average" })).toHaveValue("20");
    fireEvent.click(screen.getByRole("button", { name: "Live market data" }));
    expect(Stream.instances).toHaveLength(3);
    unmount();
    expect(last().close).toHaveBeenCalledTimes(1);
  });
});
