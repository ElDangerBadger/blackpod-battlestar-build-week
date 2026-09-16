/** Browser-local preferences only. Never read mission data or fetch market data. */
export const LOCAL_WATCHLIST_KEY = "blackpod.cabin.local-watchlist.v1";
export const MAX_LOCAL_WATCHLIST_SYMBOLS = 100;
export const MAX_LOCAL_WATCHLIST_BYTES = 8 * 1024;

export interface LocalWatchlistStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export type NormalizeWatchlistSymbolResult =
  | { readonly ok: true; readonly symbol: string }
  | { readonly ok: false; readonly message: string };

type Result<Status extends string> = {
  readonly status: Status;
  readonly symbols: readonly string[];
  readonly message: string;
};
export type ReadLocalWatchlistResult = Result<"ready" | "invalid-data" | "storage-error">;
export type ChangeLocalWatchlistResult = Result<
  "saved" | "duplicate" | "unchanged" | "invalid-symbol" | "limit" | "storage-error" | "invalid-data"
>;
export type LocalWatchlistChange = { readonly type: "add" | "remove"; readonly symbol: string };

const SYMBOL = /^\^?[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*(?:=[A-Za-z0-9]+)?$/;
const CONTROLS = /[\u0000-\u001f\u007f-\u009f]/;
const EMPTY: readonly string[] = Object.freeze([] as string[]);
const INVALID_DATA_MESSAGE = "The saved local watchlist is invalid or uses an unsupported version. Its existing data was left unchanged; editing is unavailable.";
const STORAGE_ERROR_MESSAGE = "Browser storage is unavailable. The local watchlist could not be read or saved.";

/** Accept a single ticker, not a URL, list, company name, or execution instruction. */
export function normalizeWatchlistSymbol(input: string): NormalizeWatchlistSymbolResult {
  if (typeof input !== "string" || CONTROLS.test(input)) {
    return { ok: false, message: "Enter one symbol without control characters." };
  }
  const trimmed = input.trim();
  if (!trimmed || trimmed.length > 20 || !SYMBOL.test(trimmed)) {
    return { ok: false, message: "Enter one symbol of up to 20 characters, such as AAPL, BRK.B, BTC-USD, ^GSPC, or ES=F. Spaces, URLs, and lists are not allowed." };
  }
  return { ok: true, symbol: trimmed.toUpperCase() };
}

function decode(raw: string): readonly string[] | null {
  // Avoid allocating UTF-8 bytes for a value already too large in code units.
  if (raw.length > MAX_LOCAL_WATCHLIST_BYTES || new TextEncoder().encode(raw).byteLength > MAX_LOCAL_WATCHLIST_BYTES) return null;
  let document: unknown;
  try { document = JSON.parse(raw); } catch { return null; }
  if (document === null || typeof document !== "object" || Array.isArray(document)) return null;
  const record = document as Record<string, unknown>;
  const keys = Object.keys(record);
  if (keys.length !== 2 || !keys.includes("version") || !keys.includes("symbols") || record.version !== 1 || !Array.isArray(record.symbols) || record.symbols.length > MAX_LOCAL_WATCHLIST_SYMBOLS) return null;
  const result: string[] = [];
  const seen = new Set<string>();
  for (const value of record.symbols) {
    if (typeof value !== "string") return null;
    const normalized = normalizeWatchlistSymbol(value);
    if (!normalized.ok || normalized.symbol !== value || seen.has(value)) return null;
    seen.add(value);
    result.push(value);
  }
  // After validating that every array member is a simple ticker string, the
  // only JSON property tokens can be the two top-level schema keys. Reject
  // duplicate keys rather than silently accepting JSON.parse's last value.
  if ((raw.match(/"(?:\\.|[^"\\])*"\s*:/g) ?? []).length !== 2) return null;
  return Object.freeze(result);
}

/** Storage is injected so importing this module never accesses window/localStorage. */
export function readLocalWatchlist(storage: LocalWatchlistStorage | null | undefined): ReadLocalWatchlistResult {
  if (!storage) return { status: "storage-error", symbols: EMPTY, message: STORAGE_ERROR_MESSAGE };
  let raw: string | null;
  try { raw = storage.getItem(LOCAL_WATCHLIST_KEY); }
  catch { return { status: "storage-error", symbols: EMPTY, message: STORAGE_ERROR_MESSAGE }; }
  if (raw === null) return { status: "ready", symbols: EMPTY, message: "No symbols are saved in this browser's local watchlist." };
  if (typeof raw !== "string") return { status: "invalid-data", symbols: EMPTY, message: INVALID_DATA_MESSAGE };
  const symbols = decode(raw);
  return symbols === null
    ? { status: "invalid-data", symbols: EMPTY, message: INVALID_DATA_MESSAGE }
    : { status: "ready", symbols, message: "Local watchlist loaded from this browser." };
}

/**
 * Re-read before every change rather than writing a stale UI snapshot. Browser
 * storage has no compare-and-swap: simultaneous writes still are not atomic.
 */
export function changeLocalWatchlist(
  storage: LocalWatchlistStorage | null | undefined,
  change: LocalWatchlistChange,
): ChangeLocalWatchlistResult {
  const current = readLocalWatchlist(storage);
  if (current.status !== "ready") return { status: current.status, symbols: current.symbols, message: current.message };
  const normalized = normalizeWatchlistSymbol(change.symbol);
  if (!normalized.ok) return { status: "invalid-symbol", symbols: current.symbols, message: normalized.message };
  const symbol = normalized.symbol;
  const exists = current.symbols.includes(symbol);
  if (change.type === "add" && exists) return { status: "duplicate", symbols: current.symbols, message: `${symbol} is already in this browser's local watchlist.` };
  if (change.type === "remove" && !exists) return { status: "unchanged", symbols: current.symbols, message: `${symbol} is not in this browser's local watchlist. Nothing changed.` };
  if (change.type === "add" && current.symbols.length >= MAX_LOCAL_WATCHLIST_SYMBOLS) return { status: "limit", symbols: current.symbols, message: `The local watchlist is limited to ${MAX_LOCAL_WATCHLIST_SYMBOLS} symbols.` };
  const symbols = Object.freeze(change.type === "add" ? [...current.symbols, symbol] : current.symbols.filter((entry) => entry !== symbol));
  try { storage!.setItem(LOCAL_WATCHLIST_KEY, JSON.stringify({ version: 1, symbols })); }
  catch { return { status: "storage-error", symbols: current.symbols, message: "The local watchlist could not be saved in browser storage. The change is not confirmed saved." }; }
  return { status: "saved", symbols, message: `${symbol} ${change.type === "add" ? "added to" : "removed from"} this browser's local watchlist.` };
}
