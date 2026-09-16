import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CABIN_CONTEXT_SCHEMA, NAVIGATOR_MARKET_CONTRACT } from "../contracts/cabinContext";
import type { NavigatorMarket } from "../contracts/cabinContext";
import type { NavigatorMarketVariant } from "../contracts/navigatorCatalog";
import { LOCAL_WATCHLIST_KEY } from "../data/localWatchlist";
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

const FLEET_SYMBOLS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLU", "XLB", "XLRE", "XLC", "SPY", "QQQ", "DIA", "VXZ", "IWF", "IWD", "IWM", "MTUM", "USMV", "QUAL"];

function fleetMission() {
  const bundle = capturedMission();
  const original = bundle.navigatorMarket!;
  const capture = (symbol: string, timeframe: NavigatorMarket["timeframe"], ma_period: NavigatorMarket["ma_period"], close: number, ma: number, capturedAt: string): NavigatorMarketVariant => ({
    market: {
      ...original, symbol, name: `${symbol} captured fund`, category: "index", timeframe, ma_period,
      points: original.points.map((point, index) => ({ ...point, o: close - 2, h: close + 2, l: close - 3, c: close - 1 + index, ma })),
      summary: { ...original.summary, last_price: close, last_ma: ma, ma_period },
      data: { provider: "yfinance", source: "provider", stale: false, age_seconds: 9 },
    },
    capturedAt, sourceIdentity: `capture-${symbol.toLowerCase()}`,
    navigatorGitRevision: "c".repeat(40), navigatorSourceSha256: "d".repeat(64), navigatorWorktreeDirty: true,
    reference: {
      ...artifact("navigator_fleet_market", `presentation/navigator_fleet/${symbol}-${timeframe}-ma${ma_period}.json`, NAVIGATOR_MARKET_CONTRACT),
      producer: "navigator", observed_at: capturedAt, sha256: "e".repeat(64),
    },
  });
  bundle.navigatorFleetVariants = [
    ...FLEET_SYMBOLS.map((symbol, index) => capture(symbol, "1d", 250, 300 + index, 280 + index, `2026-09-16T14:00:${String(index).padStart(2, "0")}Z`)),
    capture("XLK", "1h", 20, 331.25, 310.15, "2026-09-16T14:31:00Z"),
    capture("SPY", "1h", 20, 655.75, 620.2, "2026-09-16T14:32:00Z"),
  ];
  const evidence = new Map(bundle.evidence);
  evidence.set("oracle_normalized_snapshot", {
    name: "oracle_normalized_snapshot", status: "LOADED", message: null,
    reference: artifact("oracle_normalized_snapshot", "oracle/fleet-normalized.json"),
    document: {
      normalized_snapshot_id: "fleet-snapshot-001", fleet_id: "recorded-fleet",
      as_of: "2026-09-15T23:05:20Z", symbol_count: FLEET_SYMBOLS.length,
      symbols: FLEET_SYMBOLS.map((symbol, index) => ({ symbol, price: 100 + index, return_pct: -1.25, timestamp: "2026-09-15T20:00:00Z" })),
    },
  });
  evidence.set("oracle_measurement_diagnostics", {
    name: "oracle_measurement_diagnostics", status: "LOADED", message: null,
    reference: artifact("oracle_measurement_diagnostics", "oracle/diagnostics.json"),
    document: {
      normalized_snapshot_id: "fleet-snapshot-001",
      items: FLEET_SYMBOLS.map((symbol, index) => ({ symbol, used: index < 14, excluded: index >= 14, missing: false })),
    },
  });
  evidence.set("council_candidate_evidence", {
    name: "council_candidate_evidence", status: "LOADED", message: null,
    reference: artifact("council_candidate_evidence", "council/candidates.json"),
    document: {
      normalized_snapshot_id: "fleet-snapshot-001",
      candidates: [{ symbol: "VXZ", candidate_state: "WATCH", reasons: ["Recorded volatility context"] }],
    },
  });
  bundle.evidence = evidence;
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

  it("lists all 21 recorded fleet symbols plus the original without using local watchlist preferences", () => {
    const saved = window.localStorage.getItem(LOCAL_WATCHLIST_KEY);
    window.localStorage.setItem(LOCAL_WATCHLIST_KEY, JSON.stringify({ version: 1, symbols: ["MSFT", "UNRECORDED"] }));
    try {
      render(<NavigatorReferenceTape mission={createMissionViewModel(fleetMission())} onOpenNavigator={vi.fn()} />);
      const picker = screen.getByRole("combobox", { name: "Reference tape symbol" });
      expect(within(picker).getAllByRole("option").map((option) => (option as HTMLOptionElement).value)).toEqual(["AAPL", ...FLEET_SYMBOLS]);
      expect(picker).toHaveValue("AAPL");
      expect(within(picker).queryByRole("option", { name: /MSFT|UNRECORDED/ })).not.toBeInTheDocument();
      expect(window.localStorage.getItem(LOCAL_WATCHLIST_KEY)).toBe(JSON.stringify({ version: 1, symbols: ["MSFT", "UNRECORDED"] }));
    } finally {
      if (saved === null) window.localStorage.removeItem(LOCAL_WATCHLIST_KEY);
      else window.localStorage.setItem(LOCAL_WATCHLIST_KEY, saved);
    }
  });

  it("switches same-pair fleet prices, times, and provenance without leaking original AAPL facts", () => {
    const bundle = fleetMission();
    render(<NavigatorReferenceTape mission={createMissionViewModel(bundle)} initialSymbol="XLK" onOpenNavigator={vi.fn()} />);
    const prices = screen.getByRole("region", { name: "Price snapshot" });
    const timing = screen.getByRole("region", { name: "Capture timing" });
    expect(fact(prices, "Latest captured close")).toHaveTextContent("$300.00");
    expect(fact(prices, "Supplied MA250")).toHaveTextContent("$280.00");
    expect(fact(timing, "Capture time")).toHaveTextContent("Sep 16, 2026, 2:00:00 PM UTC");
    expect(screen.getByText("Capture source: capture-xlk")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open selected Navigator market artifact" })).toHaveAttribute("href", "./demo/approved/presentation/navigator_fleet/XLK-1d-ma250.json");
    expect(screen.getByText(/Navigator revision:/)).toHaveTextContent("c".repeat(40));
    expect(screen.getByText(/Backend source SHA-256:/)).toHaveTextContent("d".repeat(64));
    expect(screen.getByText(/Backend source SHA-256:/)).toHaveTextContent("includes uncommitted source changes");
    expect(screen.getByText(/Artifact SHA-256:/)).toHaveTextContent("e".repeat(64));
    expect(screen.getByLabelText("Navigator market provenance")).toHaveTextContent("Provider cache age at capture: 9s");
    const fleet = screen.getByRole("region", { name: "Recorded fleet item" });
    expect(fact(fleet, "Fleet captured price · source units")).toHaveTextContent(/^100$/);
    expect(fact(fleet, "Fleet snapshot time")).toHaveTextContent("Sep 15, 2026, 11:05:20 PM UTC");

    fireEvent.change(screen.getByRole("combobox", { name: "Reference tape symbol" }), { target: { value: "SPY" } });
    expect(screen.getByRole("combobox", { name: "Reference tape bar interval" })).toHaveValue("1d");
    expect(screen.getByRole("combobox", { name: "Reference tape moving average" })).toHaveValue("250");
    expect(fact(prices, "Latest captured close")).toHaveTextContent("$311.00");
    expect(fact(prices, "Supplied MA250")).toHaveTextContent("$291.00");
    expect(fact(timing, "Capture time")).toHaveTextContent("Sep 16, 2026, 2:00:11 PM UTC");
    expect(screen.getByText("Capture source: capture-spy")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Open selected Navigator market artifact" });
    expect(link).toHaveAttribute("href", "./demo/approved/presentation/navigator_fleet/SPY-1d-ma250.json");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
    expect(screen.queryByText("AAPL · Apple Inc.")).not.toBeInTheDocument();
    expect(screen.queryByText("Capture source: captured-navigator-reference")).not.toBeInTheDocument();
    expect(screen.queryByText("Capture source: capture-xlk")).not.toBeInTheDocument();
    expect(screen.queryByText("$215.00")).not.toBeInTheDocument();
    expect(screen.queryByText("$202.20")).not.toBeInTheDocument();
  });

  it("preserves the chosen interval and MA across symbols and opens that exact captured dataset", () => {
    const onOpenNavigator = vi.fn();
    render(<NavigatorReferenceTape mission={createMissionViewModel(fleetMission())} initialSymbol="XLK" onOpenNavigator={onOpenNavigator} />);
    fireEvent.change(screen.getByRole("combobox", { name: "Reference tape bar interval" }), { target: { value: "1h" } });
    expect(screen.getByRole("combobox", { name: "Reference tape moving average" })).toHaveValue("20");
    expect(fact(screen.getByRole("region", { name: "Price snapshot" }), "Latest captured close")).toHaveTextContent("$331.25");
    fireEvent.change(screen.getByRole("combobox", { name: "Reference tape symbol" }), { target: { value: "SPY" } });
    expect(screen.getByRole("combobox", { name: "Reference tape bar interval" })).toHaveValue("1h");
    expect(screen.getByRole("combobox", { name: "Reference tape moving average" })).toHaveValue("20");
    expect(fact(screen.getByRole("region", { name: "Price snapshot" }), "Latest captured close")).toHaveTextContent("$655.75");
    expect(fact(screen.getByRole("region", { name: "Price snapshot" }), "Supplied MA20")).toHaveTextContent("$620.20");
    expect(fact(screen.getByRole("region", { name: "Capture timing" }), "Capture time")).toHaveTextContent("Sep 16, 2026, 2:32:00 PM UTC");
    expect(onOpenNavigator).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Open full Navigator" }));
    expect(onOpenNavigator).toHaveBeenCalledExactlyOnceWith("SPY", { symbol: "SPY", timeframe: "1h", ma_period: 20 });
  });

  it("keeps uncaptured fleet observations and Oracle exclusions readable without inventing chart prices or averages", () => {
    const bundle = fleetMission();
    bundle.navigatorFleetVariants = bundle.navigatorFleetVariants!.filter((entry) => entry.market.symbol !== "VXZ");
    render(<NavigatorReferenceTape mission={createMissionViewModel(bundle)} initialSymbol="VXZ" onOpenNavigator={vi.fn()} />);
    expect(screen.getByRole("combobox", { name: "Reference tape symbol" })).toHaveValue("VXZ");
    expect(screen.getByRole("status")).toHaveTextContent("No Navigator chart capture is available for VXZ");
    expect(screen.queryByRole("region", { name: "Price snapshot" })).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Reference tape moving average" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open full Navigator" })).not.toBeInTheDocument();
    const fleet = screen.getByRole("region", { name: "Recorded fleet item" });
    expect(fact(fleet, "Fleet captured price · source units")).toHaveTextContent(/^114$/);
    expect(fact(fleet, "Fleet recorded return")).toHaveTextContent("-1.25%");
    expect(fact(fleet, "Fleet observation time")).toHaveTextContent("Sep 15, 2026, 8:00:00 PM UTC");
    expect(fact(fleet, "Oracle measurement coverage")).toHaveTextContent("Excluded from Oracle");
    expect(fact(fleet, "Council candidate classification")).toHaveTextContent("WATCH");
    expect(within(fleet).getByText("Recorded volatility context")).toBeInTheDocument();
    expect(fleet).not.toHaveTextContent("$114");
    expect(screen.queryByText("$215.00")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open selected Navigator market artifact" })).not.toBeInTheDocument();
  });

  it("reads supplied fleet captures even without the original chart while withholding the full-chart action", () => {
    const bundle = fleetMission();
    bundle.navigatorMarket = null;
    bundle.cabinContext = null;
    render(<NavigatorReferenceTape mission={createMissionViewModel(bundle)} initialSymbol="SPY" onOpenNavigator={vi.fn()} />);
    expect(screen.getByText("SPY · SPY captured fund")).toBeInTheDocument();
    expect(fact(screen.getByRole("region", { name: "Price snapshot" }), "Latest captured close")).toHaveTextContent("$311.00");
    expect(screen.getByRole("link", { name: "Open selected Navigator market artifact" })).toHaveAttribute("href", "./demo/approved/presentation/navigator_fleet/SPY-1d-ma250.json");
    expect(screen.getByText(/Full Navigator is unavailable while the mission's base chart capture is missing/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open full Navigator" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Original mission reference" })).not.toBeInTheDocument();
  });

  it("labels diagnostic-only fleet rows without claiming saved observations or borrowing Navigator price and time", () => {
    const bundle = fleetMission();
    const evidence = new Map(bundle.evidence);
    evidence.delete("oracle_normalized_snapshot");
    bundle.evidence = evidence;
    render(<NavigatorReferenceTape mission={createMissionViewModel(bundle)} initialSymbol="VXZ" onOpenNavigator={vi.fn()} />);
    const fleet = screen.getByRole("region", { name: "Recorded fleet item" });
    expect(within(fleet).getByText(/The normalized snapshot is unavailable/)).toHaveTextContent(
      "Only diagnostic and candidate records for VXZ are shown; no observed fleet price, observation time, or complete fleet membership is established by these records.",
    );
    expect(fleet).not.toHaveTextContent("separate saved fleet observation");
    expect(fact(fleet, "Fleet captured price · source units")).toHaveTextContent(/^Not recorded$/);
    expect(fact(fleet, "Fleet snapshot time")).toHaveTextContent(/^Not recorded$/);
    expect(fact(fleet, "Fleet observation time")).toHaveTextContent(/^Not recorded$/);
    expect(fact(fleet, "Oracle measurement coverage")).toHaveTextContent("Excluded from Oracle");
    expect(fact(fleet, "Council candidate classification")).toHaveTextContent("WATCH");
    expect(within(fleet).getByText("Recorded volatility context")).toBeInTheDocument();
    expect(within(fleet).queryByRole("link", { name: "Observed fleet snapshot" })).not.toBeInTheDocument();
    // The independent chart capture remains readable but is not fleet evidence.
    expect(fact(screen.getByRole("region", { name: "Price snapshot" }), "Latest captured close")).toHaveTextContent("$314.00");
    expect(fleet).not.toHaveTextContent("$314.00");
    expect(fleet).not.toHaveTextContent("Sep 16, 2026, 2:00:14 PM UTC");
  });

  it("explicitly reports a removed selection without silently showing another symbol's capture", () => {
    const bundle = fleetMission();
    const onOpenNavigator = vi.fn();
    const { rerender } = render(<NavigatorReferenceTape mission={createMissionViewModel(bundle)} initialSymbol="XLK" onOpenNavigator={onOpenNavigator} />);
    fireEvent.change(screen.getByRole("combobox", { name: "Reference tape symbol" }), { target: { value: "SPY" } });
    bundle.navigatorFleetVariants = bundle.navigatorFleetVariants!.filter((entry) => entry.market.symbol !== "SPY");
    rerender(<NavigatorReferenceTape mission={createMissionViewModel(bundle)} initialSymbol="XLK" onOpenNavigator={onOpenNavigator} />);
    expect(screen.getByRole("combobox", { name: "Reference tape symbol" })).toHaveValue("SPY");
    expect(screen.getByRole("status")).toHaveTextContent("The selected capture is no longer available.");
    expect(screen.getByRole("status")).toHaveTextContent("No Navigator chart capture is available for SPY");
    expect(screen.queryByRole("region", { name: "Price snapshot" })).not.toBeInTheDocument();
    expect(screen.queryByText("AAPL · Apple Inc.")).not.toBeInTheDocument();
    expect(screen.queryByText("XLK · XLK captured fund")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open full Navigator" })).not.toBeInTheDocument();
    expect(onOpenNavigator).not.toHaveBeenCalled();
  });

  it.each([
    { name: "navigator_market" },
    { path: "presentation/navigator_fleet/SPY-1d-ma250.json" },
    { path: "presentation/navigator_fleet/XLK-1h-ma250.json" },
    { path: "presentation/navigator_fleet/XLK-1d-ma20.json" },
    { path: "../outside.json" },
    { path: "presentation/navigator_fleet/%58LK-1d-ma250.json" },
    { producer: "oracle" },
    { schema_version: "other.market.v1" },
  ])("suppresses a selected variant artifact link that does not match its exact capture: %j", (changedField) => {
    const bundle = fleetMission();
    Object.assign(bundle.navigatorFleetVariants![0].reference, changedField);
    render(<NavigatorReferenceTape mission={createMissionViewModel(bundle)} initialSymbol="XLK" onOpenNavigator={vi.fn()} />);
    expect(screen.getByText("XLK · XLK captured fund")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open selected Navigator market artifact" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Artifact SHA-256:/)).not.toBeInTheDocument();
  });

  it("links the original symbol's separate single-symbol catalog capture with its own provenance", () => {
    const bundle = fleetMission();
    const supplied = bundle.navigatorFleetVariants!.find((entry) => entry.market.symbol === "XLK" && entry.market.timeframe === "1h")!;
    bundle.navigatorVariants = [{
      ...supplied, market: { ...supplied.market, symbol: "AAPL", name: "Apple Inc." }, sourceIdentity: "single-symbol-hourly",
      reference: { ...supplied.reference, name: "navigator_market_variant", path: "presentation/navigator_variants/1h-ma20.json" },
    }];
    render(<NavigatorReferenceTape mission={createMissionViewModel(bundle)} onOpenNavigator={vi.fn()} />);
    fireEvent.change(screen.getByRole("combobox", { name: "Reference tape bar interval" }), { target: { value: "1h" } });
    expect(screen.getByText("Capture source: single-symbol-hourly")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open selected Navigator market artifact" })).toHaveAttribute("href", "./demo/approved/presentation/navigator_variants/1h-ma20.json");
    expect(screen.queryByRole("link", { name: "Open original Navigator market artifact" })).not.toBeInTheDocument();
    expect(fact(screen.getByRole("region", { name: "Price snapshot" }), "Latest captured close")).toHaveTextContent("$331.25");
  });

  it("only changes presentation selection, without network calls or mutation of source objects", () => {
    const bundle = fleetMission();
    const mission = createMissionViewModel(bundle);
    const serialize = () => JSON.stringify(bundle, (_key, value: unknown) => value instanceof Map ? [...value] : value);
    const before = serialize();
    const original = bundle.navigatorMarket;
    const captures = bundle.navigatorFleetVariants;
    const network = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("Unexpected data or model request"));
    const onOpenNavigator = vi.fn();
    try {
      render(<NavigatorReferenceTape mission={mission} initialSymbol="XLK" onOpenNavigator={onOpenNavigator} />);
      fireEvent.change(screen.getByRole("combobox", { name: "Reference tape bar interval" }), { target: { value: "1h" } });
      fireEvent.change(screen.getByRole("combobox", { name: "Reference tape symbol" }), { target: { value: "SPY" } });
      fireEvent.click(screen.getByRole("button", { name: "Original mission reference" }));
      expect(screen.getByText("AAPL · Apple Inc.")).toBeInTheDocument();
      expect(fact(screen.getByRole("region", { name: "Price snapshot" }), "Latest captured close")).toHaveTextContent("$215.00");
      expect(bundle.navigatorMarket).toBe(original);
      expect(bundle.navigatorFleetVariants).toBe(captures);
      expect(serialize()).toBe(before);
      expect(network).not.toHaveBeenCalled();
      expect(onOpenNavigator).not.toHaveBeenCalled();
    } finally {
      network.mockRestore();
    }
  });
});
