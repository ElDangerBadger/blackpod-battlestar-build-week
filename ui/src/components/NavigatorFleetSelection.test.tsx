import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { NavigatorMarket } from "../contracts/cabinContext";
import type { NavigatorMarketVariant } from "../contracts/navigatorCatalog";
import type { JsonObject } from "../contracts/presentation";
import type { MissionEvidenceName } from "../data/loadMission";
import { createMissionViewModel } from "../data/viewModel";
import { artifact, createMissionBundleFixture } from "../test/missionFixture";
import { FleetOverview } from "./FleetOverview";
import { NavigatorOceanBoundary } from "./NavigatorOceanBoundary";
import type { NavigatorOceanViewProps } from "./navigator-ocean/NavigatorOceanView";

const ORIGINAL_CAPTURED_AT = "2026-09-15T22:36:41Z";
const FLEET_CAPTURED_AT = "2026-09-16T08:15:00Z";
const SOURCE_HASH = "d".repeat(64);
const fetchSpy = vi.fn();
const noWebGL = () => false;
const hasWebGL = () => true;
const baseProps = {
  presentationMode: "LIVE" as const,
  runMode: "LIVE" as const,
  capturedAt: ORIGINAL_CAPTURED_AT,
  sourceIdentity: "original-aapl-capture",
  reducedMotion: true,
};

function market(
  symbol = "AAPL",
  price = 331.34,
  timeframe: NavigatorMarket["timeframe"] = "1d",
  period: NavigatorMarket["ma_period"] = 250,
): NavigatorMarket {
  return {
    symbol,
    name: symbol === "AAPL" ? "Apple Inc." : `${symbol} captured instrument`,
    category: symbol === "AAPL" ? "equity" : "index",
    timeframe,
    ma_period: period,
    currency: "USD",
    points: [
      { t: 1_789_430_400, o: price - 3, h: price + 1, l: price - 5, c: price - 2, v: 100, ma: price - 10, atr: 4 },
      { t: 1_789_516_800, o: price - 1, h: price + 2, l: price - 2, c: price, v: 120, ma: price - 9, atr: 4.1 },
    ],
    summary: {
      last_price: price, last_ma: price - 9, pct_vs_ma: 3.17, position: "above",
      trend_slope_pct: 0.7, volatility: "gentle", atr: 4.1, atr_pct: 1.2,
      ma_period: period, bar_count: 2,
    },
    data: { provider: "yfinance", source: "disk", stale: true, age_seconds: 42 },
    disclaimer: `${symbol} supplied capture disclaimer.`,
  };
}

function capture(
  symbol: string,
  price: number,
  timeframe: NavigatorMarket["timeframe"] = "1d",
  period: NavigatorMarket["ma_period"] = 250,
): NavigatorMarketVariant {
  return {
    market: market(symbol, price, timeframe, period),
    capturedAt: FLEET_CAPTURED_AT,
    sourceIdentity: `recorded-${symbol}-${timeframe}-ma${period}`,
    navigatorGitRevision: "c".repeat(40),
    navigatorSourceSha256: SOURCE_HASH,
    navigatorWorktreeDirty: true,
    reference: artifact("navigator_fleet_market", `presentation/navigator_fleet/${symbol}-${timeframe}-ma${period}.json`, "navigator.api.ohlc.v1"),
  };
}

function freeze<T>(value: T): T {
  if (value !== null && typeof value === "object") {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}

function selectSymbol(symbol: string) {
  fireEvent.change(screen.getByRole("combobox", { name: "Navigator review symbol" }), { target: { value: symbol } });
}

function selectedStatus() {
  return within(screen.getByRole("region", { name: "Captured Navigator datasets" })).getByRole("status");
}

function expectSvg(data: NavigatorMarket, capturedAt = FLEET_CAPTURED_AT) {
  expect(screen.getByRole("img", { name: `${data.symbol} price history with supplied ${data.ma_period}-bar moving average` })).toBeInTheDocument();
  expect(screen.getByTestId("current-price-ship")).toHaveAttribute("aria-label", `Ship at latest close $${data.points.at(-1)!.c.toFixed(2)}`);
  expect(screen.getByRole("combobox", { name: "Navigator review symbol" })).toHaveValue(data.symbol);
  expect(screen.getByRole("combobox", { name: "Captured bar interval" })).toHaveValue(data.timeframe);
  expect(screen.getByRole("combobox", { name: "Captured moving average" })).toHaveValue(String(data.ma_period));
  expect(screen.getByText(`Captured at: ${capturedAt}`)).toBeInTheDocument();
}

function fleetFixture() {
  const bundle = createMissionBundleFixture();
  const recorded: JsonObject = {
    normalized_snapshot_id: "saved-fleet-snapshot", fleet_id: "saved-oracle-fleet",
    as_of: "2026-09-15T23:05:20Z", symbol_count: 3,
    symbols: [
      { symbol: "XLK", price: 183.74, return_pct: 0.25, timestamp: "2026-09-15T20:00:00Z" },
      { symbol: "XLF", price: 52.25, return_pct: null },
      { symbol: "SPY", price: null, return_pct: null },
    ],
  };
  const diagnostics: JsonObject = {
    normalized_snapshot_id: "saved-fleet-snapshot",
    items: [{ symbol: "XLK", used: true }, { symbol: "XLF", excluded: true }],
  };
  const candidates: JsonObject = {
    normalized_snapshot_id: "saved-fleet-snapshot", fleet_id: "saved-oracle-fleet",
    candidates: [{ symbol: "XLK", candidate_state: "OBSERVE", reasons: ["Recorded observation only"] }],
  };
  const evidence = new Map(bundle.evidence);
  for (const [name, document] of Object.entries({
    oracle_normalized_snapshot: recorded,
    oracle_measurement_diagnostics: diagnostics,
    council_candidate_evidence: candidates,
  })) {
    evidence.set(name as MissionEvidenceName, {
      name: name as MissionEvidenceName, status: "LOADED", document,
      reference: artifact(name, `oracle/${name}.json`), message: null,
    });
  }
  bundle.evidence = evidence;
  bundle.navigatorMarket = market();
  bundle.navigatorFleetVariants = [capture("XLK", 512.34)];
  return { bundle, recorded, diagnostics, candidates };
}

beforeEach(() => {
  fetchSpy.mockReset();
  vi.stubGlobal("fetch", fetchSpy);
});

afterEach(() => {
  expect(fetchSpy).not.toHaveBeenCalled();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Navigator fleet capture selection", () => {
  it("uses symbol as well as interval/MA identity and forwards each exact capture to the lazy renderer", async () => {
    const original = freeze(market());
    const xlk = freeze(capture("XLK", 512.34));
    const spy = freeze({ ...capture("SPY", 677.89), capturedAt: "2026-09-16T08:16:00Z" });
    const variants = freeze([xlk, spy]);
    const before = JSON.stringify({ original, variants });
    const LazyStub = vi.fn((props: NavigatorOceanViewProps) => <p data-testid="lazy-selection">{props.data.symbol} {props.data.summary.last_price} {props.capturedAt}</p>);
    const loadView = vi.fn(async () => ({ default: LazyStub }));
    render(<NavigatorOceanBoundary {...baseProps} data={original} variants={variants} capabilityProbe={hasWebGL} loadView={loadView} />);
    expect(await screen.findByTestId("lazy-selection")).toHaveTextContent(`AAPL 331.34 ${ORIGINAL_CAPTURED_AT}`);

    for (const variant of variants) {
      selectSymbol(variant.market.symbol);
      expect(screen.getByTestId("lazy-selection")).toHaveTextContent(`${variant.market.symbol} ${variant.market.summary.last_price} ${variant.capturedAt}`);
      expect(LazyStub.mock.calls.at(-1)![0].data).toBe(variant.market);
      expect(LazyStub.mock.calls.at(-1)![0]).toMatchObject({ capturedAt: variant.capturedAt, presentationMode: "LIVE", runMode: "LIVE", reducedMotion: true });
      expect(selectedStatus()).toHaveTextContent(`${variant.sourceIdentity} · not streaming`);
    }

    fireEvent.click(screen.getByRole("button", { name: "Original mission capture" }));
    expect(LazyStub.mock.calls.at(-1)![0].data).toBe(original);
    expect(selectedStatus()).toHaveTextContent(`AAPL · 1d · MA250 · captured ${ORIGINAL_CAPTURED_AT} · original-aapl-capture · not streaming`);
    expect(loadView).toHaveBeenCalledTimes(1);
    expect(JSON.stringify({ original, variants })).toBe(before);
  });

  it("updates the real SVG prices, identity, capture time and provider provenance together", () => {
    const xlk = capture("XLK", 512.34);
    xlk.market.data = { provider: "yfinance", source: "provider", stale: false, age_seconds: 0 };
    const loadView = vi.fn();
    render(<NavigatorOceanBoundary {...baseProps} data={market()} variants={[freeze(xlk)]} capabilityProbe={noWebGL} loadView={loadView} />);
    selectSymbol("XLK");
    expectSvg(xlk.market);
    expect(screen.queryByRole("img", { name: /AAPL price history/ })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Navigator market provenance")).toHaveTextContent("Provider: yfinance · Source: provider · Not stale at capture · Provider cache age at capture: 0s. This is not a streaming quote.");
    expect(screen.getByText("XLK supplied capture disclaimer.")).toBeInTheDocument();
    expect(screen.queryByText("AAPL supplied capture disclaimer.")).not.toBeInTheDocument();
    expect(selectedStatus()).toHaveTextContent(xlk.sourceIdentity);
    expect(loadView).not.toHaveBeenCalled();
  });

  it("preserves an available interval/MA pair when switching symbols", () => {
    const hourlyAapl = capture("AAPL", 333.1, "1h", 20);
    const hourlyXlk = capture("XLK", 511.9, "1h", 20);
    render(<NavigatorOceanBoundary {...baseProps} data={market()} variants={[capture("XLK", 512.34), hourlyAapl, hourlyXlk]} capabilityProbe={noWebGL} />);
    fireEvent.change(screen.getByRole("combobox", { name: "Captured bar interval" }), { target: { value: "1h" } });
    selectSymbol("XLK");
    expectSvg(hourlyXlk.market);
    expect(selectedStatus()).toHaveTextContent(hourlyXlk.sourceIdentity);
  });

  it.each([
    { label: "same interval before another interval", original: market(), variants: [capture("XLK", 501, "1h", 250), capture("XLK", 502, "1d", 20)], expected: 1 },
    { label: "daily MA250 when the selected interval is absent", original: market("AAPL", 331.34, "1h", 20), variants: [capture("XLK", 503, "1wk", 50), capture("XLK", 504)], expected: 1 },
    { label: "the symbol's only available pair", original: market(), variants: [capture("XLK", 505, "1wk", 50)], expected: 0 },
  ])("falls back to $label without borrowing another symbol's data", ({ original, variants, expected }) => {
    render(<NavigatorOceanBoundary {...baseProps} data={original} variants={variants} capabilityProbe={noWebGL} />);
    selectSymbol("XLK");
    expectSvg(variants[expected].market);
    expect(selectedStatus()).toHaveTextContent(variants[expected].sourceIdentity);
  });

  it("limits interval and MA choices to the selected symbol, including forced unavailable changes", () => {
    const xlk = capture("XLK", 512.34);
    const xlk50 = capture("XLK", 511.27, "1d", 50);
    render(<NavigatorOceanBoundary {...baseProps} data={market()} variants={[capture("AAPL", 332, "1h", 20), xlk, xlk50]} capabilityProbe={noWebGL} />);
    selectSymbol("XLK");
    expect(screen.getByRole("option", { name: "Hourly" })).toBeDisabled();
    expect(screen.getByRole("option", { name: "MA20 bars" })).toBeDisabled();
    fireEvent.change(screen.getByRole("combobox", { name: "Captured bar interval" }), { target: { value: "1h" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Captured moving average" }), { target: { value: "20" } });
    expectSvg(xlk.market);
    fireEvent.change(screen.getByRole("combobox", { name: "Captured moving average" }), { target: { value: "50" } });
    expectSvg(xlk50.market);
  });

  it("disables a recorded fleet symbol without a capture and ignores a forced selection", () => {
    const original = market();
    render(<NavigatorOceanBoundary {...baseProps} data={original} variants={[capture("XLK", 512.34)]} fleetSymbols={["XLK", "XLF"]} capabilityProbe={noWebGL} />);
    expect(screen.getByRole("option", { name: "XLF · not captured" })).toBeDisabled();
    selectSymbol("XLF");
    expectSvg(original, ORIGINAL_CAPTURED_AT);
    expect(selectedStatus()).toHaveTextContent("AAPL · 1d · MA250");
    expect(screen.queryByRole("img", { name: /XLF/ })).not.toBeInTheDocument();
  });

  it.each([true, false])("opens an initial fleet symbol with a matching original pair when available: %s", (matchingPair) => {
    const weekly = capture("XLK", 510, "1wk", 50);
    const daily = capture("XLK", 512.34);
    render(<NavigatorOceanBoundary {...baseProps} data={market()} variants={matchingPair ? [weekly, daily] : [weekly]} initialSymbol="XLK" fleetSymbols={["XLK"]} capabilityProbe={noWebGL} />);
    expectSvg(matchingPair ? daily.market : weekly.market);
  });

  it("does not relabel the original when an initial fleet capture is unavailable", () => {
    const original = market();
    render(<NavigatorOceanBoundary {...baseProps} data={original} variants={[capture("XLK", 512.34)]} fleetSymbols={["XLF", "XLK"]} initialSymbol="XLF" capabilityProbe={noWebGL} />);
    expectSvg(original, ORIGINAL_CAPTURED_AT);
    expect(selectedStatus()).toHaveTextContent("Selected capture is no longer available; showing the original.");
    expect(selectedStatus()).toHaveTextContent("original-aapl-capture");
  });

  it.each(["SPY", "AAPL"])("opens the exact requested %s interval and MA rather than the original pair", (symbol) => {
    const requested = capture(symbol, 677.21, "1h", 20);
    render(<NavigatorOceanBoundary {...baseProps} data={market()} variants={[capture("SPY", 670), requested]}
      initialSymbol={symbol} initialCapture={{ symbol, timeframe: "1h", ma_period: 20 }} capabilityProbe={noWebGL} />);
    expectSvg(requested.market);
    expect(selectedStatus()).toHaveTextContent(requested.sourceIdentity);
    expect(selectedStatus()).not.toHaveTextContent("no longer available");
  });

  it("passes an exact Tape capture and its provenance to the lazy renderer without requiring initialSymbol", async () => {
    const requested = freeze(capture("SPY", 677.21, "1h", 20));
    const LazyStub = vi.fn((props: NavigatorOceanViewProps) => <p data-testid="lazy-selection">{props.data.symbol}</p>);
    const loadView = vi.fn(async () => ({ default: LazyStub }));
    render(<NavigatorOceanBoundary {...baseProps} data={market()} variants={[capture("SPY", 670), requested]}
      initialCapture={{ symbol: "SPY", timeframe: "1h", ma_period: 20 }} capabilityProbe={hasWebGL} loadView={loadView} />);
    expect(await screen.findByTestId("lazy-selection")).toHaveTextContent("SPY");
    expect(LazyStub.mock.calls.at(-1)![0].data).toBe(requested.market);
    expect(LazyStub.mock.calls.at(-1)![0].capturedAt).toBe(requested.capturedAt);
    expect(selectedStatus()).toHaveTextContent("SPY · 1h · MA20");
    expect(selectedStatus()).toHaveTextContent(requested.sourceIdentity);
    expect(loadView).toHaveBeenCalledOnce();
  });

  it.each([
    { symbol: "SPY", selection: { symbol: "SPY", timeframe: "1h" as const, ma_period: 20 as const } },
    { symbol: "XLK", selection: { symbol: "SPY", timeframe: "1d" as const, ma_period: 250 as const } },
  ])("announces an unavailable or mismatched exact handoff instead of quietly choosing another symbol or pair", ({ symbol, selection }) => {
    const original = market();
    render(<NavigatorOceanBoundary {...baseProps} data={original} variants={[capture("SPY", 670), capture("XLK", 512)]}
      initialSymbol={symbol} initialCapture={selection} capabilityProbe={noWebGL} />);
    expectSvg(original, ORIGINAL_CAPTURED_AT);
    expect(selectedStatus()).toHaveTextContent("Selected capture is no longer available; showing the original.");
    expect(selectedStatus()).toHaveTextContent("original-aapl-capture");
    expect(screen.queryByRole("figure", { name: /Navigator ship view for SPY|Navigator ship view for XLK/ })).not.toBeInTheDocument();
  });

  it("announces removal of a selected symbol capture and restores original values and provenance", () => {
    const original = market();
    const xlk = capture("XLK", 512.34);
    const { rerender } = render(<NavigatorOceanBoundary {...baseProps} data={original} variants={[xlk]} fleetSymbols={["XLK"]} initialSymbol="XLK" capabilityProbe={noWebGL} />);
    expectSvg(xlk.market);
    rerender(<NavigatorOceanBoundary {...baseProps} data={original} variants={[]} fleetSymbols={["XLK"]} initialSymbol="XLK" capabilityProbe={noWebGL} />);
    expectSvg(original, ORIGINAL_CAPTURED_AT);
    expect(selectedStatus()).toHaveTextContent("Selected capture is no longer available; showing the original.");
    expect(selectedStatus()).toHaveTextContent("original-aapl-capture");
    expect(screen.queryByText(/Backend source SHA-256/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Navigator market provenance")).toHaveTextContent("Source: disk · STALE at capture");
  });

  it.each([true, false])("retains the source fingerprint and accurately labels uncommitted source: %s", (dirty) => {
    const xlk = { ...capture("XLK", 512.34), navigatorWorktreeDirty: dirty };
    render(<NavigatorOceanBoundary {...baseProps} data={market()} variants={[xlk]} initialSymbol="XLK" capabilityProbe={noWebGL} />);
    fireEvent.click(screen.getByText("Capture provenance"));
    expect(screen.getByText(`Navigator revision: ${xlk.navigatorGitRevision}`)).toBeInTheDocument();
    expect(screen.getByText(`Artifact: ${xlk.reference.path}`)).toBeInTheDocument();
    expect(screen.getByText(`SHA-256: ${xlk.reference.sha256}`)).toBeInTheDocument();
    const fingerprint = screen.getByText(/Backend source SHA-256:/);
    expect(fingerprint).toHaveTextContent(SOURCE_HASH);
    if (dirty) expect(fingerprint).toHaveTextContent("includes uncommitted source changes");
    else expect(fingerprint).not.toHaveTextContent("includes uncommitted source changes");
  });
});

describe("Recorded fleet Navigator entry points", () => {
  it("dispatches the captured row symbol and leaves uncaptured rows and recorded prices unchanged", () => {
    const { bundle, recorded, diagnostics, candidates } = fleetFixture();
    const before = JSON.stringify({ recorded, diagnostics, candidates, original: bundle.navigatorMarket, variants: bundle.navigatorFleetVariants, summary: bundle.summary });
    freeze(recorded);
    freeze(diagnostics);
    freeze(candidates);
    const onOpenNavigator = vi.fn();
    render(<FleetOverview mission={createMissionViewModel(bundle)} onOpenNavigator={onOpenNavigator} />);
    const xlk = screen.getByRole("rowheader", { name: "XLK" }).closest("tr")!;
    const xlf = screen.getByRole("rowheader", { name: "XLF" }).closest("tr")!;
    expect(within(xlk).getByText("183.74")).toBeInTheDocument();
    expect(within(xlk).getByText("0.25%")).toBeInTheDocument();
    expect(within(xlk).getByText("2026-09-15T20:00:00Z")).toBeInTheDocument();
    expect(within(xlk).getByText("Used by Oracle")).toBeInTheDocument();
    expect(screen.queryByText("512.34")).not.toBeInTheDocument();
    expect(within(xlf).getByText("No chart capture")).toBeInTheDocument();
    expect(within(xlf).queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Review XLK in Navigator" }));
    expect(onOpenNavigator).toHaveBeenCalledExactlyOnceWith("XLK");
    expect(within(xlk).getByText("183.74")).toBeInTheDocument();
    expect(screen.getByText(/prices and capture time can differ from this saved fleet snapshot/)).toBeInTheDocument();
    expect(screen.getByText(/AAPL · separate supplemental chart/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /add|remove|buy|sell|trade/i })).not.toBeInTheDocument();
    expect(JSON.stringify({ recorded, diagnostics, candidates, original: bundle.navigatorMarket, variants: bundle.navigatorFleetVariants, summary: bundle.summary })).toBe(before);
  });

  it("does not reinterpret mismatched Oracle/Council evidence or replace snapshot prices with chart prices", () => {
    const { bundle, diagnostics, candidates } = fleetFixture();
    diagnostics.normalized_snapshot_id = "another-snapshot";
    candidates.normalized_snapshot_id = "another-snapshot";
    render(<FleetOverview mission={createMissionViewModel(bundle)} onOpenNavigator={vi.fn()} />);
    const xlk = screen.getByRole("rowheader", { name: "XLK" }).closest("tr")!;
    expect(within(xlk).getByText("183.74")).toBeInTheDocument();
    expect(within(xlk).getByText("Coverage not recorded")).toBeInTheDocument();
    expect(within(xlk).queryByText("Observe")).not.toBeInTheDocument();
    expect(screen.getByText(/Oracle diagnostics cannot be joined/)).toBeInTheDocument();
    expect(screen.getByText(/Candidate records cannot be joined/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review XLK in Navigator" })).toBeEnabled();
    expect(screen.queryByText("512.34")).not.toBeInTheDocument();
  });

  it("shows no chart button if the required original reference is unavailable", () => {
    const { bundle } = fleetFixture();
    bundle.navigatorMarket = null;
    render(<FleetOverview mission={createMissionViewModel(bundle)} onOpenNavigator={vi.fn()} />);
    expect(screen.getAllByText("No chart capture")).toHaveLength(3);
    expect(screen.queryByRole("button", { name: /Review .* in Navigator/ })).not.toBeInTheDocument();
    expect(screen.getByText("183.74")).toBeInTheDocument();
  });

  it("does not introduce chart actions without an integration callback", () => {
    const { bundle } = fleetFixture();
    render(<FleetOverview mission={createMissionViewModel(bundle)} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Navigator reference" })).not.toBeInTheDocument();
    expect(screen.getByText(/Filtering does not change the reference chart/)).toBeInTheDocument();
  });
});
