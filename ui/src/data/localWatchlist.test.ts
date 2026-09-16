import { describe, expect, it, vi } from "vitest";
import {
  changeLocalWatchlist, LOCAL_WATCHLIST_KEY, MAX_LOCAL_WATCHLIST_BYTES,
  MAX_LOCAL_WATCHLIST_SYMBOLS, normalizeWatchlistSymbol, readLocalWatchlist,
} from "./localWatchlist";

function storage(initial?: string) {
  const values = new Map<string, string>([["unrelated.preference", "preserved"]]);
  if (initial !== undefined) values.set(LOCAL_WATCHLIST_KEY, initial);
  return {
    values,
    getItem: vi.fn((key: string) => values.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => { values.set(key, value); }),
  };
}
const saved = (symbols: readonly string[]) => JSON.stringify({ version: 1, symbols });

describe("local watchlist symbol input", () => {
  it.each([
    ["  aapl  ", "AAPL"], ["brk.b", "BRK.B"], ["btc-usd", "BTC-USD"],
    ["^gspc", "^GSPC"], ["es=f", "ES=F"], ["7203.t", "7203.T"], ["A".repeat(20), "A".repeat(20)],
  ])("normalizes %s into a single canonical symbol", (input, expected) => {
    expect(normalizeWatchlistSymbol(input)).toEqual({ ok: true, symbol: expected });
  });

  it.each(["", "   ", "AA PL", "A\tAPL", "AAPL\n", "\u0000AAPL", "AAPL\u007f", "AAPL\u0085", "<AAPL>", "https://example.com", "//example.com", "AAPL,MSFT", "AAPL/MSFT", "AAPL;MSFT", "AAPL@NYSE", "A".repeat(21), "ß", "A..B", ".AAPL", "BTC-", "^^GSPC", "ES==F"])("rejects unsafe or unsupported symbol input %j", (input) => {
    expect(normalizeWatchlistSymbol(input).ok).toBe(false);
  });
});

describe("local watchlist storage reads", () => {
  it("starts empty and does not seed or write anything when no local list exists", () => {
    const store = storage();
    const result = readLocalWatchlist(store);
    expect(result).toMatchObject({ status: "ready", symbols: [] });
    expect(Object.isFrozen(result.symbols)).toBe(true);
    expect(store.getItem).toHaveBeenCalledWith(LOCAL_WATCHLIST_KEY);
    expect(store.setItem).not.toHaveBeenCalled();
    expect(store.values.size).toBe(1);
  });

  it("reads the exact supported schema without changing its bytes", () => {
    const raw = '{ "symbols": ["BRK.B", "BTC-USD", "^GSPC", "ES=F"], "version": 1 }';
    const store = storage(raw);
    const result = readLocalWatchlist(store);
    expect(result).toMatchObject({ status: "ready", symbols: ["BRK.B", "BTC-USD", "^GSPC", "ES=F"] });
    expect(Object.isFrozen(result.symbols)).toBe(true);
    expect(store.values.get(LOCAL_WATCHLIST_KEY)).toBe(raw);
    expect(store.setItem).not.toHaveBeenCalled();
  });

  it.each([
    "", "{broken", "null", "[]", "true", '{"version":2,"symbols":[]}',
    '{"version":"1","symbols":[]}', '{"symbols":[]}', '{"version":1,"symbols":"AAPL"}',
    '{"version":2,"version":1,"symbols":[]}', '{"version":1,"symbols":["NVDA"],"symbols":[]}',
    '{"version":1,"symbols":[],"extra":true}', saved(["aapl"]), saved([" AAPL"]),
    saved(["AAPL", "AAPL"]), saved(["AAPL", "aapl"]), '{"version":1,"symbols":[123]}',
    saved(["AAPL,MSFT"]), saved(["A".repeat(21)]), saved(Array.from({ length: 101 }, (_, index) => `T${index}`)),
  ])("preserves invalid or unsupported stored bytes: %s", (raw) => {
    const store = storage(raw);
    expect(readLocalWatchlist(store)).toMatchObject({ status: "invalid-data", symbols: [] });
    expect(changeLocalWatchlist(store, { type: "add", symbol: "AAPL" }).status).toBe("invalid-data");
    expect(changeLocalWatchlist(store, { type: "remove", symbol: "AAPL" }).status).toBe("invalid-data");
    expect(store.values.get(LOCAL_WATCHLIST_KEY)).toBe(raw);
    expect(store.setItem).not.toHaveBeenCalled();
  });

  it("enforces the 8 KiB stored-byte limit without attempting repair", () => {
    const raw = `${" ".repeat(MAX_LOCAL_WATCHLIST_BYTES)}${saved([])}`;
    const store = storage(raw);
    expect(readLocalWatchlist(store).status).toBe("invalid-data");
    expect(store.values.get(LOCAL_WATCHLIST_KEY)).toBe(raw);
    expect(store.setItem).not.toHaveBeenCalled();
  });

  it("allows exactly 8 KiB of valid JSON but not one extra byte", () => {
    const payload = saved([]);
    const raw = `${" ".repeat(MAX_LOCAL_WATCHLIST_BYTES - payload.length)}${payload}`;
    expect(readLocalWatchlist(storage(raw)).status).toBe("ready");
    expect(readLocalWatchlist(storage(` ${raw}`)).status).toBe("invalid-data");
  });

  it("reports unavailable storage or throwing getters without writing", () => {
    expect(readLocalWatchlist(null).status).toBe("storage-error");
    expect(readLocalWatchlist(undefined).status).toBe("storage-error");
    const store = storage();
    store.getItem.mockImplementation(() => { throw new Error("blocked"); });
    expect(readLocalWatchlist(store).status).toBe("storage-error");
    expect(changeLocalWatchlist(store, { type: "add", symbol: "AAPL" }).status).toBe("storage-error");
    expect(store.setItem).not.toHaveBeenCalled();
  });
});

describe("local watchlist mutations", () => {
  it("saves canonical additions and removals only to the namespaced preference key", () => {
    const store = storage();
    expect(changeLocalWatchlist(store, { type: "add", symbol: " aapl " })).toMatchObject({ status: "saved", symbols: ["AAPL"] });
    expect(changeLocalWatchlist(store, { type: "add", symbol: "msft" })).toMatchObject({ status: "saved", symbols: ["AAPL", "MSFT"] });
    expect(changeLocalWatchlist(store, { type: "remove", symbol: " aaPL " })).toMatchObject({ status: "saved", symbols: ["MSFT"] });
    expect(store.values.get(LOCAL_WATCHLIST_KEY)).toBe(saved(["MSFT"]));
    expect(store.values.get("unrelated.preference")).toBe("preserved");
    expect(store.setItem.mock.calls.every(([key]) => key === LOCAL_WATCHLIST_KEY)).toBe(true);
  });

  it("detects duplicates case-insensitively without rewriting the list", () => {
    const raw = saved(["AAPL"]);
    const store = storage(raw);
    expect(changeLocalWatchlist(store, { type: "add", symbol: " aApL " })).toMatchObject({ status: "duplicate", symbols: ["AAPL"] });
    expect(store.values.get(LOCAL_WATCHLIST_KEY)).toBe(raw);
    expect(store.setItem).not.toHaveBeenCalled();
  });

  it("treats removal of an absent symbol as an explicit no-op", () => {
    const store = storage(saved(["AAPL"]));
    expect(changeLocalWatchlist(store, { type: "remove", symbol: "MSFT" })).toMatchObject({ status: "unchanged", symbols: ["AAPL"] });
    expect(store.setItem).not.toHaveBeenCalled();
  });

  it("keeps the current symbols after invalid input without writing", () => {
    const store = storage(saved(["AAPL"]));
    expect(changeLocalWatchlist(store, { type: "add", symbol: "AAPL,MSFT" })).toMatchObject({ status: "invalid-symbol", symbols: ["AAPL"] });
    expect(store.setItem).not.toHaveBeenCalled();
  });

  it("limits additions to 100 symbols while allowing duplicates and removals to behave normally", () => {
    const symbols = Array.from({ length: MAX_LOCAL_WATCHLIST_SYMBOLS }, (_, index) => `T${index}`);
    const store = storage(saved(symbols));
    expect(changeLocalWatchlist(store, { type: "add", symbol: "AAPL" })).toMatchObject({ status: "limit", symbols });
    expect(changeLocalWatchlist(store, { type: "add", symbol: "t0" }).status).toBe("duplicate");
    expect(store.setItem).not.toHaveBeenCalled();
    expect(changeLocalWatchlist(store, { type: "remove", symbol: "T0" }).status).toBe("saved");
    expect(changeLocalWatchlist(store, { type: "add", symbol: "AAPL" }).status).toBe("saved");
    expect(readLocalWatchlist(store).symbols).toHaveLength(100);
  });

  it("re-reads another tab's saved changes before adding or removing", () => {
    const store = storage(saved(["AAPL"]));
    const staleView = readLocalWatchlist(store);
    store.values.set(LOCAL_WATCHLIST_KEY, saved(["AAPL", "NVDA"]));
    expect(changeLocalWatchlist(store, { type: "add", symbol: "MSFT" })).toMatchObject({ status: "saved", symbols: ["AAPL", "NVDA", "MSFT"] });
    store.values.set(LOCAL_WATCHLIST_KEY, saved(["AAPL", "NVDA", "MSFT", "BRK.B"]));
    expect(changeLocalWatchlist(store, { type: "remove", symbol: "AAPL" })).toMatchObject({ status: "saved", symbols: ["NVDA", "MSFT", "BRK.B"] });
    expect(staleView.symbols).toEqual(["AAPL"]);
  });

  it("refuses mutation if another tab replaced good data with unsupported data", () => {
    const store = storage(saved(["AAPL"]));
    readLocalWatchlist(store);
    const unsupported = '{"version":2,"symbols":["NVDA"]}';
    store.values.set(LOCAL_WATCHLIST_KEY, unsupported);
    expect(changeLocalWatchlist(store, { type: "add", symbol: "MSFT" }).status).toBe("invalid-data");
    expect(store.values.get(LOCAL_WATCHLIST_KEY)).toBe(unsupported);
    expect(store.setItem).not.toHaveBeenCalled();
  });

  it("does not claim a failed write was saved or return the proposed list as persisted", () => {
    const raw = saved(["AAPL"]);
    const store = storage(raw);
    store.setItem.mockImplementation(() => { throw new Error("quota exceeded"); });
    const result = changeLocalWatchlist(store, { type: "add", symbol: "NVDA" });
    expect(result).toMatchObject({ status: "storage-error", symbols: ["AAPL"] });
    expect(result.message).toContain("not confirmed saved");
    expect(store.values.get(LOCAL_WATCHLIST_KEY)).toBe(raw);
  });

  it("persists an explicit empty list after removing the final symbol", () => {
    const store = storage(saved(["AAPL"]));
    const result = changeLocalWatchlist(store, { type: "remove", symbol: "AAPL" });
    expect(result).toMatchObject({ status: "saved", symbols: [] });
    expect(Object.isFrozen(result.symbols)).toBe(true);
    expect(store.values.get(LOCAL_WATCHLIST_KEY)).toBe(saved([]));
  });
});
