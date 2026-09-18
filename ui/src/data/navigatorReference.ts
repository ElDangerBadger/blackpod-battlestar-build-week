import type { NavigatorReferenceFeed, NavigatorReferenceSelection, NavigatorReferenceSnapshot, NavigatorReferenceStatus } from "../contracts/navigatorReference";
import { parseNavigatorMarket } from "./validateCabinContext";

export const NAVIGATOR_REFERENCE_INTERVAL_MS = 60_000;
export const NAVIGATOR_REFERENCE_TIMEOUT_MS = 10_000;
// The canonical snapshot is capped at 2 MiB; reserve bounded space for its
// transport envelope and JSON serialization overhead.
export const NAVIGATOR_REFERENCE_MAX_BYTES = 2 * 1024 * 1024 + 64 * 1024;
const SKEW_MS = 5_000;

function require(value: unknown): asserts value {
  if (!value) throw new Error("Current Navigator reference is unavailable or failed validation.");
}
function object(value: unknown, fields: string): Record<string, unknown> {
  require(value && typeof value === "object" && !Array.isArray(value));
  require(Object.keys(value).sort().join("|") === fields.split(" ").sort().join("|"));
  return value as Record<string, unknown>;
}
function timestamp(value: unknown): number {
  require(typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|\+00:00)$/.test(value));
  const parsed = Date.parse(value);
  require(Number.isFinite(parsed) && new Date(parsed).toISOString().slice(0, 19) === value.slice(0, 19));
  return parsed;
}
function epoch(value: unknown): number {
  require(typeof value === "number" && Number.isSafeInteger(value) && value > 0);
  return value * 1000;
}

export function navigatorReferenceUrl(publicationId: string | null, selection: NavigatorReferenceSelection | null): string | null {
  if (!publicationId || !/^[a-f0-9]{64}$/.test(publicationId) || !selection
    || !/^[A-Z][A-Z0-9.-]{0,14}$/.test(selection.symbol)
    || !["1h", "1d", "1wk"].includes(selection.timeframe) || ![20, 50, 100, 200, 250].includes(selection.ma_period)) return null;
  return `/live/navigator/reference/${publicationId}/${encodeURIComponent(selection.symbol)}/${selection.timeframe}/${selection.ma_period}`;
}

export function validateNavigatorReference(value: unknown, selection: NavigatorReferenceSelection, now = Date.now()): NavigatorReferenceFeed {
  const feed = object(value, "schema_version status checked_at message snapshot");
  require(feed.schema_version === "blackpod.navigator_reference_feed.v1"
    && ["READY", "STALE", "UNAVAILABLE", "NOT_CONFIGURED"].includes(feed.status as string)
    && typeof feed.message === "string" && feed.message.length <= 500 && !/[\x00-\x1f\x7f]/.test(feed.message));
  const checked = timestamp(feed.checked_at);
  require(checked <= now + SKEW_MS);
  if (feed.snapshot === null) {
    require(feed.status !== "READY" && feed.status !== "STALE");
    return feed as unknown as NavigatorReferenceFeed;
  }
  require(feed.status === "READY" || feed.status === "STALE");
  const snapshot = object(feed.snapshot, "schema_version snapshot_id captured_at provider_fetched_at symbol timeframe ma_period bar_policy latest_bar_at expected_bar_at valid_until calendar_id provider adjustment market");
  require(snapshot.schema_version === "navigator.reference_snapshot.v1"
    && typeof snapshot.snapshot_id === "string" && /^[a-f0-9]{64}$/.test(snapshot.snapshot_id)
    && snapshot.symbol === selection.symbol && snapshot.timeframe === selection.timeframe && snapshot.ma_period === selection.ma_period
    && snapshot.provider === "yfinance" && snapshot.adjustment === "auto_adjust=True"
    && snapshot.bar_policy === "completed_regular_session"
    && typeof snapshot.calendar_id === "string" && /^sentry-session-calendar-[a-f0-9]{64}$/.test(snapshot.calendar_id));
  const captured = timestamp(snapshot.captured_at), fetched = timestamp(snapshot.provider_fetched_at);
  const validUntil = timestamp(snapshot.valid_until);
  const latest = epoch(snapshot.latest_bar_at), expected = epoch(snapshot.expected_bar_at);
  require(fetched <= captured + SKEW_MS && captured <= checked + SKEW_MS
    && latest === expected && latest <= fetched && expected <= checked + SKEW_MS
    && captured < validUntil && validUntil <= captured + 10 * 86_400_000);
  const market = parseNavigatorMarket(snapshot.market, selection.symbol, "LIVE");
  require(market.timeframe === selection.timeframe && market.ma_period === selection.ma_period
    && market.points.length <= 20_000 && market.points.at(-1)?.t === snapshot.latest_bar_at
    && market.data?.provider === "yfinance" && market.data.stale === false && market.summary.last_ma !== null);
  require(market.points.every((point) => point.l <= Math.min(point.o, point.c) && Math.max(point.o, point.c) <= point.h));
  // The server validates the snapshot digest against its original serialized
  // bytes. Re-encoding Python floats in JavaScript is not a hash verification.
  return { ...feed, snapshot: { ...snapshot, market } } as unknown as NavigatorReferenceFeed;
}

export function navigatorReferenceStatus(status: NavigatorReferenceStatus, snapshot: NavigatorReferenceSnapshot | null, now = Date.now()): NavigatorReferenceStatus {
  return snapshot && (status !== "READY" || Date.parse(snapshot.valid_until) <= now) ? "STALE" : status;
}

export async function loadNavigatorReference(url: string, selection: NavigatorReferenceSelection, signal: AbortSignal): Promise<NavigatorReferenceFeed> {
  const response = await fetch(url, { signal, cache: "no-store", headers: { Accept: "application/json" } });
  require(response.ok);
  const declared = response.headers.get("content-length");
  if (declared !== null) require(/^\d+$/.test(declared) && Number(declared) <= NAVIGATOR_REFERENCE_MAX_BYTES);
  let bytes: Uint8Array;
  if (response.body) {
    const reader = response.body.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        size += value.byteLength;
        require(size <= NAVIGATOR_REFERENCE_MAX_BYTES);
        chunks.push(value);
      }
      bytes = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    } catch (error) { await reader.cancel(); throw error; }
    finally { reader.releaseLock(); }
  } else {
    bytes = new Uint8Array(await response.arrayBuffer());
    require(bytes.length <= NAVIGATOR_REFERENCE_MAX_BYTES);
  }
  return validateNavigatorReference(JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)), selection);
}
