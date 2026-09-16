import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { JsonObject } from "../contracts/presentation";
import type { MissionEvidenceName } from "../data/loadMission";
import { LOCAL_WATCHLIST_KEY, MAX_LOCAL_WATCHLIST_SYMBOLS } from "../data/localWatchlist";
import { createMissionViewModel, type MissionViewModel } from "../data/viewModel";
import { artifact, createMissionBundleFixture } from "../test/missionFixture";
import { LocalWatchlist } from "./LocalWatchlist";

const encode = (symbols: readonly string[]) => JSON.stringify({ version: 1, symbols });

function memoryStorage(initial: string | null = null) {
  let raw = initial;
  return {
    getItem: vi.fn((_key: string) => raw),
    setItem: vi.fn((_key: string, value: string) => { raw = value; }),
    replaceRaw(value: string | null) { raw = value; },
    raw() { return raw; },
  };
}

function plainMission() {
  return createMissionViewModel(createMissionBundleFixture());
}

function capturedMission(): MissionViewModel {
  const bundle = createMissionBundleFixture();
  bundle.navigatorMarket = {
    symbol: "AAPL", name: "Apple Inc.", category: "equity", timeframe: "1d", ma_period: 250, currency: "USD",
    points: [{ t: 1789516800, o: 330, h: 333, l: 329, c: 331, v: 100, ma: 280, atr: 4 }],
    summary: { last_price: 331, last_ma: 280, pct_vs_ma: 18, position: "above", trend_slope_pct: 1, volatility: "high", atr: 4, atr_pct: 1.2, ma_period: 250, bar_count: 1 },
  };
  const documents: Partial<Record<MissionEvidenceName, JsonObject>> = {
    oracle_normalized_snapshot: {
      normalized_snapshot_id: "snapshot-watchlist-test", fleet_id: "fleet-recorded", as_of: "2026-09-15T23:00:00Z", symbol_count: 1,
      symbols: [{ symbol: "XLK", price: 183.74, return_pct: 0.5 }],
    },
    oracle_measurement_diagnostics: {
      normalized_snapshot_id: "snapshot-watchlist-test", items: [{ symbol: "XLK", used: true, excluded: false }],
    },
  };
  const evidence = new Map(bundle.evidence);
  for (const [name, document] of Object.entries(documents)) {
    evidence.set(name as MissionEvidenceName, {
      name: name as MissionEvidenceName, reference: artifact(name, `recorded/${name}.json`),
      document, status: "LOADED", message: null,
    });
  }
  bundle.evidence = evidence;
  return createMissionViewModel(bundle);
}

function add(symbol: string) {
  fireEvent.change(screen.getByRole("textbox", { name: "Symbol" }), { target: { value: symbol } });
  return fireEvent.submit(screen.getByRole("form", { name: "Add to local watchlist" }));
}

function storedSymbols(storage: ReturnType<typeof memoryStorage>): string[] {
  return JSON.parse(storage.raw() ?? encode([])).symbols;
}

function symbolRow(symbol: string): HTMLElement {
  return screen.getByRole("button", { name: `Remove ${symbol} from local watchlist` }).closest("li")!;
}

function storageEvent(key: string | null = LOCAL_WATCHLIST_KEY, newValue: string | null = null) {
  act(() => window.dispatchEvent(new StorageEvent("storage", { key, newValue })));
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("LocalWatchlist", () => {
  it("starts empty without seeding from captured mission symbols or writing storage", () => {
    const storage = memoryStorage();
    render(<LocalWatchlist mission={capturedMission()} storage={storage} />);
    expect(screen.getByRole("region", { name: "Local watchlist" })).toBeInTheDocument();
    expect(screen.getByText("Your local watchlist is empty. Add a symbol above to begin.")).toBeInTheDocument();
    expect(screen.getByText("0 of 100 local symbols")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Local watchlist symbols" })).not.toBeInTheDocument();
    expect(storage.getItem).toHaveBeenCalledWith(LOCAL_WATCHLIST_KEY);
    expect(storage.setItem).not.toHaveBeenCalled();
    expect(screen.getByText(/Entries are unverified labels, not new Harbor members or holdings/)).toBeInTheDocument();
  });

  it("uses browser storage by default without an initial write", () => {
    const getItem = vi.spyOn(Storage.prototype, "getItem").mockReturnValue(null);
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {});
    render(<LocalWatchlist mission={plainMission()} />);
    expect(getItem).toHaveBeenCalledWith(LOCAL_WATCHLIST_KEY);
    expect(setItem).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox", { name: "Symbol" })).toBeEnabled();
  });

  it("normalizes a submitted symbol, persists only the local list, and prevents form navigation", () => {
    const storage = memoryStorage();
    render(<LocalWatchlist mission={plainMission()} storage={storage} />);
    expect(add("  brk.b  ")).toBe(false);
    expect(storedSymbols(storage)).toEqual(["BRK.B"]);
    expect(storage.setItem).toHaveBeenCalledExactlyOnceWith(LOCAL_WATCHLIST_KEY, encode(["BRK.B"]));
    expect(screen.getByRole("textbox", { name: "Symbol" })).toHaveValue("");
    expect(screen.getByRole("textbox", { name: "Symbol" })).toHaveFocus();
    expect(screen.getByRole("status")).toHaveTextContent("BRK.B added to this browser's local watchlist.");
    expect(within(symbolRow("BRK.B")).getByText(/No captured fleet or Navigator evidence/)).toBeInTheDocument();
  });

  it("announces duplicate symbols without writing or duplicating the saved entry", () => {
    const storage = memoryStorage(encode(["AAPL"]));
    render(<LocalWatchlist mission={plainMission()} storage={storage} />);
    add(" aapl ");
    expect(storage.setItem).not.toHaveBeenCalled();
    expect(screen.getAllByRole("button", { name: "Remove AAPL from local watchlist" })).toHaveLength(1);
    expect(screen.getByRole("status")).toHaveTextContent("AAPL is already in this browser's local watchlist.");
    expect(screen.getByRole("textbox", { name: "Symbol" })).not.toHaveAttribute("aria-invalid", "true");
  });

  it.each(["", "AAPL MSFT", "AAPL,MSFT", "https://example.com", "<script>alert(1)</script>", "A".repeat(21)])("rejects invalid input %j without persisting it", (value) => {
    const storage = memoryStorage();
    const { container } = render(<LocalWatchlist mission={plainMission()} storage={storage} />);
    add(value);
    expect(storage.setItem).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox", { name: "Symbol" })).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("status")).toHaveTextContent("Enter one symbol");
    expect(screen.queryByRole("list", { name: "Local watchlist symbols" })).not.toBeInTheDocument();
    expect(container.querySelector("script, img")).toBeNull();
    fireEvent.change(screen.getByRole("textbox", { name: "Symbol" }), { target: { value: "MSFT" } });
    expect(screen.getByRole("textbox", { name: "Symbol" })).not.toHaveAttribute("aria-invalid", "true");
  });

  it("removes entries, returns focus to the add input, and retains changes on remount", () => {
    const storage = memoryStorage(encode(["AAPL", "XLK"]));
    const view = render(<LocalWatchlist mission={plainMission()} storage={storage} />);
    const remove = screen.getByRole("button", { name: "Remove AAPL from local watchlist" });
    remove.focus();
    fireEvent.click(remove);
    expect(storedSymbols(storage)).toEqual(["XLK"]);
    expect(screen.queryByRole("button", { name: "Remove AAPL from local watchlist" })).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Symbol" })).toHaveFocus();
    expect(screen.getByRole("status")).toHaveTextContent("AAPL removed from this browser's local watchlist.");
    view.unmount();
    render(<LocalWatchlist mission={plainMission()} storage={storage} />);
    expect(screen.getByRole("button", { name: "Remove XLK from local watchlist" })).toBeInTheDocument();
    expect(storage.setItem).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Remove XLK from local watchlist" }));
    expect(screen.getByRole("textbox", { name: "Symbol" })).toHaveFocus();
    expect(screen.getByText(/Your local watchlist is empty/)).toBeInTheDocument();
    expect(storedSymbols(storage)).toEqual([]);
  });

  it("disables editing when storage is explicitly unavailable", () => {
    render(<LocalWatchlist mission={plainMission()} storage={null} />);
    expect(screen.getByRole("textbox", { name: "Symbol" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Add symbol" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Browser storage is unavailable");
    expect(screen.getByRole("button", { name: "Retry reading local watchlist" })).toBeEnabled();
    expect(screen.getByText("No readable local list to display.")).toBeInTheDocument();
  });

  it("handles a blocked browser-storage getter without throwing", () => {
    vi.spyOn(window, "localStorage", "get").mockImplementation(() => { throw new Error("Storage denied"); });
    render(<LocalWatchlist mission={plainMission()} />);
    expect(screen.getByRole("textbox", { name: "Symbol" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Browser storage is unavailable");
  });

  it("recovers from a read failure only after a successful retry without writing", () => {
    const storage = memoryStorage(encode(["XLK"]));
    storage.getItem.mockImplementationOnce(() => { throw new Error("Read denied"); });
    render(<LocalWatchlist mission={plainMission()} storage={storage} />);
    expect(screen.getByRole("button", { name: "Add symbol" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Retry reading local watchlist" }));
    expect(screen.getByRole("button", { name: "Add symbol" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Remove XLK from local watchlist" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Local watchlist loaded from browser storage.");
    expect(storage.setItem).not.toHaveBeenCalled();
  });

  it("does not claim an unsaved write succeeded and allows retrying without losing the original list", () => {
    const storage = memoryStorage(encode(["AAPL"]));
    storage.setItem.mockImplementationOnce(() => { throw new Error("Quota exceeded"); });
    render(<LocalWatchlist mission={plainMission()} storage={storage} />);
    screen.getByRole("textbox", { name: "Symbol" }).focus();
    add("MSFT");
    expect(storedSymbols(storage)).toEqual(["AAPL"]);
    expect(screen.getByRole("status")).toHaveTextContent("The change is not confirmed saved.");
    expect(screen.queryByRole("button", { name: "Remove MSFT from local watchlist" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove AAPL from local watchlist" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "Symbol" })).toHaveValue("MSFT");
    expect(screen.getByRole("textbox", { name: "Symbol" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Retry reading local watchlist" })).toHaveFocus();
    expect(screen.getByText(/last successfully loaded version/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry reading local watchlist" }));
    expect(screen.getByRole("textbox", { name: "Symbol" })).toHaveFocus();
    expect(storage.setItem).toHaveBeenCalledTimes(1);
    fireEvent.submit(screen.getByRole("form", { name: "Add to local watchlist" }));
    expect(storedSymbols(storage)).toEqual(["AAPL", "MSFT"]);
    expect(screen.getByRole("button", { name: "Remove MSFT from local watchlist" })).toBeEnabled();
    expect(screen.getByRole("status")).toHaveTextContent("MSFT added");
  });

  it.each(["{broken", JSON.stringify({ version: 9, symbols: ["AAPL"] })])("preserves invalid saved data %j and keeps the editor disabled", (raw) => {
    const storage = memoryStorage(raw);
    render(<LocalWatchlist mission={plainMission()} storage={storage} />);
    expect(screen.getByRole("status")).toHaveTextContent("invalid or uses an unsupported version");
    expect(screen.getByRole("textbox", { name: "Symbol" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Add symbol" })).toBeDisabled();
    fireEvent.submit(screen.getByRole("form", { name: "Add to local watchlist" }));
    fireEvent.click(screen.getByRole("button", { name: "Retry reading local watchlist" }));
    expect(storage.raw()).toBe(raw);
    expect(storage.setItem).not.toHaveBeenCalled();
  });

  it("rereads matching storage events rather than trusting event payloads and never writes on synchronization", () => {
    const storage = memoryStorage(encode(["AAPL"]));
    render(<LocalWatchlist mission={plainMission()} storage={storage} />);
    storage.replaceRaw(encode(["XLK"]));
    storageEvent(LOCAL_WATCHLIST_KEY, encode(["DO-NOT-TRUST-PAYLOAD"]));
    expect(screen.getByRole("button", { name: "Remove XLK from local watchlist" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove AAPL from local watchlist" })).not.toBeInTheDocument();
    expect(screen.queryByText("DO-NOT-TRUST-PAYLOAD")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("updated from browser storage");
    const reads = storage.getItem.mock.calls.length;
    storageEvent("unrelated-preference", encode(["MSFT"]));
    expect(storage.getItem).toHaveBeenCalledTimes(reads);
    act(() => window.dispatchEvent(new StorageEvent("storage", { key: LOCAL_WATCHLIST_KEY, storageArea: window.sessionStorage })));
    expect(storage.getItem).toHaveBeenCalledTimes(reads);
    storage.replaceRaw(null);
    storageEvent(null);
    expect(screen.getByText(/Your local watchlist is empty/)).toBeInTheDocument();
    expect(storage.setItem).not.toHaveBeenCalled();
  });

  it("preserves the last loaded list and disables edits after corrupt cross-tab data", () => {
    const storage = memoryStorage(encode(["AAPL"]));
    render(<LocalWatchlist mission={plainMission()} storage={storage} />);
    storage.replaceRaw("{broken");
    storageEvent();
    expect(screen.getByRole("button", { name: "Remove AAPL from local watchlist" })).toBeDisabled();
    expect(screen.getByText("1 of 100 local symbols · last loaded")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("invalid or uses an unsupported version");
    expect(storage.raw()).toBe("{broken");
    expect(storage.setItem).not.toHaveBeenCalled();
    storage.replaceRaw(encode(["MSFT"]));
    fireEvent.click(screen.getByRole("button", { name: "Retry reading local watchlist" }));
    expect(screen.getByRole("button", { name: "Remove MSFT from local watchlist" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Remove AAPL from local watchlist" })).not.toBeInTheDocument();
  });

  it("rereads storage before mutations so a stale component does not overwrite a newer tab's symbols", () => {
    const storage = memoryStorage(encode(["AAPL"]));
    render(<LocalWatchlist mission={plainMission()} storage={storage} />);
    storage.replaceRaw(encode(["AAPL", "XLK"]));
    add("MSFT");
    expect(storedSymbols(storage)).toEqual(["AAPL", "XLK", "MSFT"]);
    expect(screen.getByRole("button", { name: "Remove XLK from local watchlist" })).toBeInTheDocument();
    storage.replaceRaw(encode(["AAPL", "XLK", "MSFT", "BRK.B"]));
    fireEvent.click(screen.getByRole("button", { name: "Remove AAPL from local watchlist" }));
    expect(storedSymbols(storage)).toEqual(["XLK", "MSFT", "BRK.B"]);
    expect(screen.getByRole("button", { name: "Remove BRK.B from local watchlist" })).toBeInTheDocument();
  });

  it("refreshes stale displayed symbols even when a newly submitted label is invalid", () => {
    const storage = memoryStorage(encode(["AAPL"]));
    render(<LocalWatchlist mission={plainMission()} storage={storage} />);
    storage.replaceRaw(encode(["AAPL", "XLK"]));
    add("not a symbol");
    expect(screen.getByRole("textbox", { name: "Symbol" })).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("button", { name: "Remove XLK from local watchlist" })).toBeInTheDocument();
    expect(storedSymbols(storage)).toEqual(["AAPL", "XLK"]);
    expect(storage.setItem).not.toHaveBeenCalled();
  });

  it("blocks the hundred-and-first symbol but still permits removals and replacement", () => {
    const symbols = Array.from({ length: MAX_LOCAL_WATCHLIST_SYMBOLS }, (_, index) => `SYM${index}`);
    const storage = memoryStorage(encode(symbols));
    render(<LocalWatchlist mission={plainMission()} storage={storage} />);
    add("MSFT");
    expect(screen.getByRole("status")).toHaveTextContent("limited to 100 symbols");
    expect(storage.setItem).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Add symbol" })).toBeEnabled();
    expect(screen.getByText("100 of 100 local symbols")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove SYM0 from local watchlist" }));
    add("MSFT");
    expect(storedSymbols(storage)).toHaveLength(100);
    expect(storedSymbols(storage)).toContain("MSFT");
    expect(storedSymbols(storage)).not.toContain("SYM0");
  });

  it("labels current-mission Navigator, captured-fleet, and absent evidence separately", () => {
    const storage = memoryStorage(encode(["AAPL", "XLK", "MSFT"]));
    const view = render(<LocalWatchlist mission={capturedMission()} storage={storage} />);
    expect(within(symbolRow("AAPL")).getByText("Navigator capture available in this mission.")).toBeInTheDocument();
    expect(within(symbolRow("AAPL")).queryByText(/Recorded in the captured fleet/)).not.toBeInTheDocument();
    expect(within(symbolRow("XLK")).getByText("Recorded in the captured fleet · Used by Oracle.")).toBeInTheDocument();
    expect(within(symbolRow("MSFT")).getByText("No captured fleet or Navigator evidence for this symbol in this mission.")).toBeInTheDocument();
    view.rerender(<LocalWatchlist mission={plainMission()} storage={storage} />);
    expect(within(symbolRow("AAPL")).getByText(/No captured fleet or Navigator evidence/)).toBeInTheDocument();
    expect(within(symbolRow("XLK")).getByText(/No captured fleet or Navigator evidence/)).toBeInTheDocument();
    expect(storedSymbols(storage)).toEqual(["AAPL", "XLK", "MSFT"]);
    expect(storage.setItem).not.toHaveBeenCalled();
  });

  it("labels fallback rows as analytical evidence rather than captured fleet membership", () => {
    const current = capturedMission();
    const evidence = new Map(current.evidence);
    evidence.delete("oracle_normalized_snapshot");
    render(<LocalWatchlist mission={{ ...current, evidence }} storage={memoryStorage(encode(["XLK"]))} />);
    expect(within(symbolRow("XLK")).getByText("Recorded in analytical evidence · Used by Oracle.")).toBeInTheDocument();
    expect(screen.queryByText(/Recorded in the captured fleet/)).not.toBeInTheDocument();
  });

  it("does not fetch or mutate canonical evidence, chart data, or mission permissions while adding and removing", () => {
    const current = capturedMission();
    const before = structuredClone(current);
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const storage = memoryStorage();
    render(<LocalWatchlist mission={current} storage={storage} />);
    add("MSFT");
    add("XLK");
    fireEvent.click(screen.getByRole("button", { name: "Remove XLK from local watchlist" }));
    expect(fetch).not.toHaveBeenCalled();
    expect(current).toEqual(before);
    expect(current.market.navigatorMarket?.symbol).toBe("AAPL");
    expect(storedSymbols(storage)).toEqual(["MSFT"]);
    expect(screen.queryByRole("button", { name: /buy|sell|execute|approve|refresh|run mission/i })).not.toBeInTheDocument();
  });
});
