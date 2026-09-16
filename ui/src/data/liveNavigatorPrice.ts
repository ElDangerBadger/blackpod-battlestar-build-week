/** Ephemeral market-data messages. Never evidence and never persisted in a mission. */
export const LIVE_PRICE_MAX_AGE_MS = 60_000;
export const LIVE_PRICE_RETRY_MS = 5_000;
export const LIVE_PRICE_CLOCK_SKEW_MS = 5_000;
export const LIVE_PRICE_SILENCE_MS = 20_000;

export type LiveNavigatorPriceStatus = "CONNECTING" | "LIVE" | "WAITING" | "STALE" | "UNAVAILABLE";
export type LiveNavigatorPriceEvent = Readonly<{
  schema_version: "navigator.live_price.v1";
  symbol: string;
  provider: "alpaca";
  feed: "iex" | "sip";
  status: LiveNavigatorPriceStatus;
  price: number | null;
  trade_at: string | null;
  received_at: string | null;
  checked_at: string;
  message: string;
}>;

const FIELDS = ["schema_version", "symbol", "provider", "feed", "status", "price", "trade_at", "received_at", "checked_at", "message"].sort();
const STATUSES = new Set(["CONNECTING", "LIVE", "WAITING", "STALE", "UNAVAILABLE"]);

export function navigatorPublicationId(baseUrl: string): string | null {
  return /^\/?live\/revisions\/([a-f0-9]{64})\/$/.exec(baseUrl)?.[1] ?? null;
}

export function liveNavigatorPriceUrl(publicationId: string | null, symbol: string): string | null {
  if (!publicationId || !/^[a-f0-9]{64}$/.test(publicationId) || !/^[A-Z][A-Z0-9.-]{0,14}$/.test(symbol)) return null;
  return `/live/navigator/price/${publicationId}/${encodeURIComponent(symbol)}`;
}

function utc(value: unknown, now: number): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$/.test(value)) return false;
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) && timestamp <= now + LIVE_PRICE_CLOCK_SKEW_MS && new Date(timestamp).toISOString().slice(0, 19) === value.slice(0, 19);
}

/** Retain sub-millisecond order from Alpaca trade timestamps. */
function nanos(timestamp: string): bigint {
  const seconds = Date.parse(`${timestamp.slice(0, 19)}Z`);
  const fraction = /\.(\d+)Z$/.exec(timestamp)?.[1] ?? "";
  return BigInt(seconds) * 1_000_000n + BigInt(fraction.padEnd(9, "0"));
}

export function validateLiveNavigatorPrice(
  value: unknown, symbol: string, now = Date.now(), previous: LiveNavigatorPriceEvent | null = null,
): LiveNavigatorPriceEvent {
  const invalid = () => { throw new Error("Live market-data message is unavailable or invalid."); };
  if (!value || typeof value !== "object" || Array.isArray(value)) return invalid();
  const item = value as Record<string, unknown>;
  if (Object.keys(item).sort().join("|") !== FIELDS.join("|")
    || item.schema_version !== "navigator.live_price.v1" || item.symbol !== symbol || item.provider !== "alpaca"
    || !["iex", "sip"].includes(item.feed as string) || !STATUSES.has(item.status as string)
    || typeof item.message !== "string" || item.message.length > 200 || /[\x00-\x1f\x7f]/.test(item.message)
    || !utc(item.checked_at, now)) return invalid();
  const quoted = item.price !== null;
  if (quoted) {
    if (typeof item.price !== "number" || !Number.isFinite(item.price) || item.price <= 0
      || !utc(item.trade_at, now) || !utc(item.received_at, now)
      || nanos(item.trade_at) - nanos(item.received_at) > BigInt(LIVE_PRICE_CLOCK_SKEW_MS) * 1_000_000n
      || nanos(item.received_at) - nanos(item.checked_at) > BigInt(LIVE_PRICE_CLOCK_SKEW_MS) * 1_000_000n) return invalid();
  } else if (item.trade_at !== null || item.received_at !== null || item.status === "LIVE") return invalid();
  const result = item as LiveNavigatorPriceEvent;
  if (previous && previous.symbol === symbol) {
    if (result.feed !== previous.feed) return invalid();
    if (nanos(result.checked_at) < nanos(previous.checked_at)) return invalid();
    if (result.trade_at && previous.trade_at && (nanos(result.trade_at) < nanos(previous.trade_at)
      || (nanos(result.trade_at) === nanos(previous.trade_at) && result.price !== previous.price))) return invalid();
    if (result.received_at && previous.received_at && nanos(result.received_at) < nanos(previous.received_at)) return invalid();
  }
  return result;
}

export function livePriceStatus(event: LiveNavigatorPriceEvent, now = Date.now()): LiveNavigatorPriceStatus {
  if (event.status === "LIVE" && event.trade_at !== null && now - Date.parse(event.trade_at) >= LIVE_PRICE_MAX_AGE_MS) return "STALE";
  return event.status;
}
