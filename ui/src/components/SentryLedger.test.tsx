import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SentryFeed, SentrySnapshot } from "../contracts/sentry";
import { LOCAL_WATCHLIST_KEY } from "../data/localWatchlist";
import { useSentryFeed, type SentryFeedState } from "../data/useSentryFeed";
import { createMissionViewModel } from "../data/viewModel";
import { createMissionBundleFixture } from "../test/missionFixture";
import { SentryLedger } from "./SentryLedger";

vi.mock("../data/useSentryFeed", () => ({ useSentryFeed: vi.fn() }));
const feedHook = vi.mocked(useSentryFeed);
const checked = "2026-09-16T23:00:00Z";
const observed = "2026-07-15T15:00:00Z";

function observation(overrides: Partial<SentrySnapshot> = {}): SentrySnapshot {
  const score = { total_score: 71.25, contributions: [{ factor: "volume_ratio", contribution: 12, observed_value: 3, threshold: 2, reason: "Supplied volume exceeded the configured threshold." }], reasons: ["Recorded score explanation."], warnings: [], missing_data_fields: [] };
  return {
    schema_version: "microcap_sentry.snapshot.v1", event_id: "event-a", observed_at: observed, symbol: "FAKE", classification: "IGNITION",
    eligibility: { eligible: true, reasons: ["Supplied profile passed eligibility."], warnings: [], missing_fields: [] },
    features: { price_change_1m_pct: 2.25, price_change_5m_pct: 8.5, price_change_15m_pct: null, distance_from_session_high_pct: null, distance_from_vwap_pct: null, new_session_high: null, volume_ratio_1m: 3, volume_ratio_5m: 2, volume_acceleration: null, cumulative_relative_volume: null, spread_pct: null, dollar_volume: 12500, quote_imbalance: null, executable_liquidity_warning: false, warnings: ["Quote depth not supplied."], missing_data_fields: ["spread_pct"] },
    powder_keg: score, ignition: { ...score, total_score: 82.75 }, continuation: null, symbol_profile: null,
    catalysts: [], news_events: [], filing_events: [], halt_events: [], risks: ["Liquidity may be limited in supplied data."], missing_information: ["No supplied halt history."], reasons: ["Price and volume rules were met at the supplied cutoff."],
    observation_only: true, order_submission_enabled: false, ...overrides,
  };
}
function feed(entries = [observation()], kind: "RESEARCH" | "RECORDED" = "RESEARCH"): SentryFeed {
  return { schema_version: "blackpod.sentry_feed.v1", status: "READY", checked_at: checked, message: "Archive read.", source: { label: "Canonical Sentry archive", kind, file_name: "observations.jsonl", sha256: "a".repeat(64), byte_size: 4500, latest_observed_at: entries.length ? entries.map((entry) => entry.observed_at).sort().at(-1)! : null, raw_count: entries.length + 2, duplicate_count: 2 }, observations: entries };
}
function ready(value = feed()): SentryFeedState { return { status: "READY", feed: value, message: "", refreshing: false, refresh: vi.fn() }; }
function mission(captured = false) {
  const bundle = createMissionBundleFixture();
  if (captured) bundle.navigatorMarket = { symbol: "AAPL", name: "Apple Inc.", category: "equity", timeframe: "1d", ma_period: 250, currency: "USD", points: [{ t: 1789516800, o: 330, h: 333, l: 329, c: 331, v: 100, ma: 280, atr: 4 }], summary: { last_price: 331, last_ma: 280, pct_vs_ma: 18, position: "above", trend_slope_pct: 1, volatility: "high", atr: 4, atr_pct: 1.2, ma_period: 250, bar_count: 1 } };
  return createMissionViewModel(bundle);
}
function show(state = ready(), captured = false) {
  feedHook.mockReturnValue(state);
  const onOpenNavigator = vi.fn();
  return { ...render(<SentryLedger enabled mission={mission(captured)} onOpenNavigator={onOpenNavigator} />), onOpenNavigator };
}
beforeEach(() => { vi.resetAllMocks(); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("SentryLedger", () => {
  it("clearly distinguishes synthetic archived observations, source dates and duplicate counts", () => {
    show();
    expect(screen.getByRole("heading", { name: "Synthetic research archive — not live detections" })).toBeInTheDocument();
    expect(screen.getByText("3 total · 2 exact duplicates collapsed · 1 distinct observations")).toBeInTheDocument();
    expect(screen.getByText("observations.jsonl")).toBeInTheDocument();
    expect(screen.getByText("a".repeat(64))).toBeInTheDocument();
    expect(screen.getAllByText(/Jul 15, 2026/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Sep 16, 2026, 23:00:00 UTC/)).toBeInTheDocument();
    expect(screen.getByText(/Observation time is not the time this page was checked/)).toBeInTheDocument();
  });

  it("shows raw scores without probability or causal claims and preserves missing values", () => {
    const { container } = show();
    expect(screen.getByText("71.25")).toBeInTheDocument();
    expect(screen.getByText("82.75")).toBeInTheDocument();
    expect(screen.getByText(/not probabilities, forecasts, or trading recommendations/)).toBeInTheDocument();
    expect(screen.getByText("Price and volume rules were met at the supplied cutoff.")).toBeInTheDocument();
    expect(screen.getByText("No supplied halt history.")).toBeInTheDocument();
    expect(screen.getByText("spread_pct")).toBeInTheDocument();
    expect(screen.getByText("Quote depth not supplied.")).toBeInTheDocument();
    expect(screen.getAllByText(/Weight: Not recorded/)).toHaveLength(2);
    const metrics = screen.getByRole("region", { name: "Recorded market measurements" });
    expect(within(metrics).getByText("2.25%")).toBeInTheDocument();
    expect(within(metrics).getAllByText("Not recorded").length).toBeGreaterThan(0);
    expect(container.textContent).not.toContain("71.25%");
    expect(container.textContent).not.toContain("caused the price");
  });

  it("filters symbols and any historical classification, retaining observation history", () => {
    show(ready(feed([observation(), observation({ event_id: "event-old", observed_at: "2026-07-14T15:00:00Z", classification: "HALTED" }), observation({ event_id: "event-other", symbol: "OTHER", classification: "DORMANT" })])));
    fireEvent.change(screen.getByRole("searchbox", { name: "Find a symbol" }), { target: { value: "oth" } });
    expect(screen.getByRole("button", { name: "Review OTHER Sentry observations" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Review FAKE Sentry observations" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Recorded classification" }), { target: { value: "HALTED" } });
    expect(screen.getByRole("heading", { name: "FAKE Halted" })).toBeInTheDocument();
    expect(screen.getByText(/1 of 2 symbols · 3 distinct observations/)).toBeInTheDocument();
    const history = screen.getByRole("combobox", { name: "Observation history · 2 distinct records" });
    expect(within(history).getAllByRole("option")).toHaveLength(2);
    fireEvent.change(history, { target: { value: "event-a" } });
    expect(screen.getByRole("heading", { name: "FAKE Ignition" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Recorded classification" })).toHaveValue("");
  });

  it("orders timestamp ties by event ID without inventing a latest classification", () => {
    show(ready(feed([observation({ event_id: "event-z", classification: "HALTED" }), observation({ event_id: "event-a", classification: "DORMANT" })])));
    expect(screen.getByRole("heading", { name: "FAKE Dormant" })).toBeInTheDocument();
    expect(screen.getByText(/no classification wins the tie/)).toBeInTheDocument();
    const history = screen.getByRole("combobox", { name: "Observation history · 2 distinct records" });
    expect(within(history).getAllByRole("option").map((option) => (option as HTMLOptionElement).value)).toEqual(["event-a", "event-z"]);
    fireEvent.change(history, { target: { value: "event-z" } });
    expect(screen.getByRole("heading", { name: "FAKE Halted" })).toBeInTheDocument();
  });

  it("preserves sub-millisecond observation ordering", () => {
    show(ready(feed([observation({ event_id: "event-a", observed_at: "2026-07-15T15:00:00.000001Z", classification: "DORMANT" }), observation({ event_id: "event-z", observed_at: "2026-07-15T15:00:00.000002Z", classification: "IGNITION" })])));
    expect(screen.getByRole("heading", { name: "FAKE Ignition" })).toBeInTheDocument();
    expect(screen.queryByText(/no classification wins the tie/)).not.toBeInTheDocument();
  });

  it("never adds research labels to storage or opens Navigator even for a matching capture", () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const { onOpenNavigator } = show(ready(feed([observation({ symbol: "AAPL" })])), true);
    const add = screen.getByRole("button", { name: "Add AAPL to local watchlist" });
    const navigator = screen.getByRole("button", { name: "Review AAPL in Navigator" });
    expect(add).toBeDisabled(); expect(navigator).toBeDisabled();
    fireEvent.click(add); fireEvent.click(navigator);
    expect(setItem).not.toHaveBeenCalled(); expect(onOpenNavigator).not.toHaveBeenCalled();
    expect(screen.getByText(/fictional labels must not be presented as verified securities/)).toBeInTheDocument();
  });

  it("only writes the local watchlist after an explicit recorded-symbol action", () => {
    vi.spyOn(Storage.prototype, "getItem").mockReturnValue(null);
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {});
    show(ready(feed([observation({ symbol: "AAPL" })], "RECORDED")));
    expect(setItem).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Add AAPL to local watchlist" }));
    expect(setItem).toHaveBeenCalledExactlyOnceWith(LOCAL_WATCHLIST_KEY, JSON.stringify({ version: 1, symbols: ["AAPL"] }));
    expect(screen.getByText("AAPL added to this browser's local watchlist.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review AAPL in Navigator" })).toBeDisabled();
    expect(screen.getByText(/No Navigator capture is attached/)).toBeInTheDocument();
  });

  it("reports local storage write failure without claiming the symbol was saved", () => {
    vi.spyOn(Storage.prototype, "getItem").mockReturnValue(null);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("quota"); });
    show(ready(feed([observation({ symbol: "AAPL" })], "RECORDED")));
    fireEvent.click(screen.getByRole("button", { name: "Add AAPL to local watchlist" }));
    expect(screen.getByText(/The change is not confirmed saved/)).toBeInTheDocument();
    expect(screen.queryByText("AAPL added to this browser's local watchlist.")).not.toBeInTheDocument();
  });

  it("opens only an available captured Navigator symbol", () => {
    const { onOpenNavigator } = show(ready(feed([observation({ symbol: "AAPL" })], "RECORDED")), true);
    fireEvent.click(screen.getByRole("button", { name: "Review AAPL in Navigator" }));
    expect(onOpenNavigator).toHaveBeenCalledExactlyOnceWith("AAPL");
  });

  it("retains but marks unavailable evidence and disables symbol actions on refresh failure", () => {
    show({ ...ready(feed([observation({ symbol: "AAPL" })], "RECORDED")), status: "UNAVAILABLE", message: "Archive request failed." }, true);
    expect(screen.getByText("Observation source unavailable")).toBeInTheDocument();
    expect(screen.getByText(/Showing the last successfully read archive/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "AAPL Ignition" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add AAPL to local watchlist" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Review AAPL in Navigator" })).toBeDisabled();
  });

  it.each(["NOT_CONFIGURED", "UNAVAILABLE", "LOADING"] as const)("does not interpret %s as no candidates or all-clear", (status) => {
    show({ ...ready(), status, feed: null, message: "No source was read." });
    expect(screen.getByText(/This does not mean there are no candidates or risks/)).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Sentry recorded symbols" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Add .* to local watchlist/ })).not.toBeInTheDocument();
  });

  it("keeps empty archives and no filter matches distinct", () => {
    const view = show(ready(feed([])));
    expect(screen.getByText(/An empty archive does not establish/)).toBeInTheDocument();
    view.unmount();
    show();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "NOT-HERE" } });
    expect(screen.getByText("No recorded symbols match these filters.")).toBeInTheDocument();
    expect(screen.queryByText(/An empty archive does not establish/)).not.toBeInTheDocument();
  });

  it("refreshes only through the read-only hook and honors the enabled boundary", () => {
    const state = ready();
    const view = show(state);
    fireEvent.click(screen.getByRole("button", { name: "Refresh records" }));
    expect(state.refresh).toHaveBeenCalledOnce();
    expect(feedHook).toHaveBeenLastCalledWith({ enabled: true });
    view.rerender(<SentryLedger enabled={false} mission={mission()} onOpenNavigator={vi.fn()} />);
    expect(feedHook).toHaveBeenLastCalledWith({ enabled: false });
    expect(screen.getByRole("button", { name: "Refresh records" })).toBeDisabled();
  });

  it("renders source text and original JSON as inert text, never executable HTML", () => {
    const payload = '<img src=x onerror="window.pwned=true">';
    const { container } = show(ready(feed([observation({ reasons: [payload] })])));
    expect(screen.getByText(payload)).toBeInTheDocument();
    expect(container.querySelector("img, script, iframe")).toBeNull();
    const original = container.querySelector("pre")!;
    expect(original.textContent).toContain(JSON.stringify(payload));
    expect(original.textContent).toContain('"order_submission_enabled": false');
  });
});
