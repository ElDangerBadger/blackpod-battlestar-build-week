import { SENTRY_CLASSIFICATIONS, type SentryFeed } from "../contracts/sentry";

export const SENTRY_FEED_URL = "/live/sentry/current.json";
export const SENTRY_MAX_BYTES = 8 * 1024 * 1024;
export const SENTRY_MAX_ROWS = 1000;
const invalid = (): never => { throw new Error("Sentry archive response is unavailable or invalid."); };
type RecordValue = Record<string, unknown>;
function record(value: unknown, required: string[], optional: string[] = []): RecordValue {
  if (!value || typeof value !== "object" || Array.isArray(value)) return invalid();
  const result = value as RecordValue;
  if (required.some((key) => !Object.hasOwn(result, key))
    || Object.keys(result).some((key) => !required.includes(key) && !optional.includes(key))) return invalid();
  return result;
}
function text(value: unknown, max = 4000, empty = false): asserts value is string {
  if (typeof value !== "string" || value.length > max || (!empty && !value.trim())
    || /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(value)) invalid();
}
function finite(value: unknown, nullable = false): asserts value is number | null {
  if ((nullable && value === null) || (typeof value === "number" && Number.isFinite(value)
    && (!Number.isInteger(value) || Number.isSafeInteger(value)))) return;
  invalid();
}
function integer(value: unknown, max = Number.MAX_SAFE_INTEGER): asserts value is number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0 || value > max) invalid();
}
function bool(value: unknown, nullable = false): void {
  if (typeof value !== "boolean" && !(nullable && value === null)) invalid();
}
function timestamp(value: unknown, utcOnly = false): asserts value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$/.test(value)
    || (utcOnly && !value.endsWith("Z")) || !Number.isFinite(Date.parse(value))) return invalid();
  // Check local calendar components without silently normalizing February 30 or 24:00.
  const local = `${value.slice(0, 19)}Z`;
  if (!Number.isFinite(Date.parse(local)) || new Date(local).toISOString().slice(0, 19) !== value.slice(0, 19)) invalid();
}
function nanos(value: string): bigint {
  const wholeSeconds = value.replace(/\.\d+(Z|[+-]\d{2}:\d{2})$/, "$1");
  return BigInt(Date.parse(wholeSeconds)) * 1_000_000n
    + BigInt((/\.(\d+)(?:Z|[+-]\d{2}:\d{2})$/.exec(value)?.[1] ?? "").padEnd(9, "0"));
}
function list(value: unknown, check: (item: unknown) => void): asserts value is unknown[] {
  if (!Array.isArray(value) || value.length > SENTRY_MAX_ROWS) return invalid();
  value.forEach(check);
}
function strings(value: unknown): void { list(value, (item) => text(item)); }
function symbol(value: unknown, expected?: string): asserts value is string {
  if (typeof value !== "string" || !/^[A-Z][A-Z0-9.-]{0,14}$/.test(value) || (expected !== undefined && value !== expected)) invalid();
}
function primitive(value: unknown): void {
  if (value === null || typeof value === "boolean") return;
  if (typeof value === "number") finite(value);
  else text(value);
}
function factor(value: unknown): void {
  const item = record(value, ["factor", "contribution", "observed_value", "threshold", "reason"], ["configured_weight"]);
  text(item.factor, 256); text(item.reason, 4000, true); finite(item.contribution);
  primitive(item.observed_value); primitive(item.threshold);
  if (Object.hasOwn(item, "configured_weight")) finite(item.configured_weight, true);
}
function score(value: unknown, nullable: boolean): void {
  const item = record(value, ["total_score", "contributions", "reasons", "warnings", "missing_data_fields"]);
  finite(item.total_score, nullable);
  if (item.total_score !== null && (item.total_score < 0 || item.total_score > 100)) invalid();
  list(item.contributions, factor); strings(item.reasons); strings(item.warnings); strings(item.missing_data_fields);
}
const FEATURE_NUMBERS = ["price_change_1m_pct", "price_change_5m_pct", "price_change_15m_pct", "distance_from_session_high_pct",
  "distance_from_vwap_pct", "volume_ratio_1m", "volume_ratio_5m", "volume_acceleration", "cumulative_relative_volume", "spread_pct", "dollar_volume", "quote_imbalance"];
function features(value: unknown): void {
  const item = record(value, [...FEATURE_NUMBERS, "new_session_high", "executable_liquidity_warning", "warnings", "missing_data_fields"]);
  FEATURE_NUMBERS.forEach((key) => finite(item[key], true));
  bool(item.new_session_high, true); bool(item.executable_liquidity_warning);
  strings(item.warnings); strings(item.missing_data_fields);
}
const PROFILE_NUMBERS = ["price", "market_cap", "float_shares", "average_daily_dollar_volume", "short_interest_pct", "days_to_cover", "breakout_proximity_pct"];
const PROFILE_BOOLEANS = ["recent_material_filing", "active_shelf", "warrant_overhang", "recent_reverse_split"];
function profile(value: unknown, expected: string): void {
  const item = record(value, [...PROFILE_NUMBERS, ...PROFILE_BOOLEANS, "symbol", "exchange", "volatility_compression", "prior_spike_count"]);
  symbol(item.symbol, expected);
  if (item.exchange !== null) text(item.exchange, 256);
  PROFILE_NUMBERS.forEach((key) => { const number = item[key]; finite(number, true); if (number !== null && number < 0) invalid(); });
  PROFILE_BOOLEANS.forEach((key) => bool(item[key], true));
  if (typeof item.volatility_compression !== "boolean") {
    finite(item.volatility_compression, true);
    if (item.volatility_compression !== null && item.volatility_compression < 0) invalid();
  }
  if (item.prior_spike_count !== null) integer(item.prior_spike_count);
}
function eventBase(item: RecordValue, expected: string): void {
  symbol(item.symbol, expected); timestamp(item.timestamp);
  if ("event_id" in item) text(item.event_id, 256);
}
function catalyst(value: unknown, expected: string): void {
  const item = record(value, ["symbol", "timestamp", "catalyst_type", "summary", "material", "source_event_id", "confidence"]);
  eventBase(item, expected); text(item.summary, 4000, true); bool(item.material, true);
  if (typeof item.catalyst_type !== "string" || !["NEWS", "SEC_FILING", "TRADING_HALT", "OTHER"].includes(item.catalyst_type)) invalid();
  if (item.source_event_id !== null) text(item.source_event_id, 256);
  finite(item.confidence, true);
  if (item.confidence !== null && (item.confidence < 0 || item.confidence > 1)) invalid();
}
function news(value: unknown, expected: string): void {
  const item = record(value, ["event_id", "symbol", "timestamp", "headline", "summary", "source", "material"]);
  eventBase(item, expected); text(item.headline); text(item.summary, 4000, true); text(item.source, 256); bool(item.material, true);
}
function filing(value: unknown, expected: string): void {
  const booleans = ["material", "is_new", "dilution_risk", "active_shelf", "warrant_overhang", "reverse_split"];
  const item = record(value, ["event_id", "symbol", "timestamp", "form_type", "summary", "accession_number", ...booleans]);
  eventBase(item, expected); text(item.form_type, 256); text(item.summary, 4000, true);
  if (item.accession_number !== null) text(item.accession_number, 256);
  booleans.forEach((key) => bool(item[key], true));
}
function halt(value: unknown, expected: string): void {
  const item = record(value, ["event_id", "symbol", "timestamp", "active", "reason", "halt_code", "resumed_at"]);
  eventBase(item, expected); bool(item.active); text(item.reason, 4000, true);
  if (item.halt_code !== null) text(item.halt_code, 256);
  if (item.resumed_at !== null) timestamp(item.resumed_at);
}
function snapshot(value: unknown): void {
  const item = record(value, ["schema_version", "event_id", "observed_at", "symbol", "classification", "eligibility", "features",
    "powder_keg", "ignition", "symbol_profile", "continuation", "catalysts", "news_events", "filing_events", "halt_events",
    "risks", "missing_information", "reasons", "observation_only", "order_submission_enabled"]);
  if (item.schema_version !== "microcap_sentry.snapshot.v1" || item.observation_only !== true || item.order_submission_enabled !== false
    || typeof item.classification !== "string" || !(SENTRY_CLASSIFICATIONS as readonly string[]).includes(item.classification)) invalid();
  text(item.event_id, 256); timestamp(item.observed_at); symbol(item.symbol);
  const expected = item.symbol;
  const eligibility = record(item.eligibility, ["eligible", "reasons", "warnings", "missing_fields"]);
  bool(eligibility.eligible); strings(eligibility.reasons); strings(eligibility.warnings); strings(eligibility.missing_fields);
  features(item.features); score(item.powder_keg, false); score(item.ignition, false);
  if (item.continuation !== null) score(item.continuation, true);
  if (item.symbol_profile !== null) profile(item.symbol_profile, expected);
  list(item.catalysts, (entry) => catalyst(entry, expected)); list(item.news_events, (entry) => news(entry, expected));
  list(item.filing_events, (entry) => filing(entry, expected)); list(item.halt_events, (entry) => halt(entry, expected));
  strings(item.risks); strings(item.missing_information); strings(item.reasons);
}

/** Validate without mutating, normalizing, scoring or filling absent canonical values. */
export function validateSentryFeed(value: unknown, now = Date.now()): SentryFeed {
  const item = record(value, ["schema_version", "status", "checked_at", "message", "source", "observations"]);
  if (item.schema_version !== "blackpod.sentry_feed.v1" || !["READY", "NOT_CONFIGURED", "UNAVAILABLE"].includes(item.status as string)) invalid();
  timestamp(item.checked_at, true); text(item.message, 256);
  if (Date.parse(item.checked_at) > now + 5000) invalid();
  list(item.observations, snapshot);
  const observations = item.observations as SentryFeed["observations"];
  if (new Set(observations.map((entry) => entry.event_id)).size !== observations.length) invalid();
  if (item.status !== "READY") {
    if (item.source !== null || observations.length !== 0) invalid();
    return item as unknown as SentryFeed;
  }
  const source = record(item.source, ["label", "kind", "file_name", "sha256", "byte_size", "latest_observed_at", "raw_count", "duplicate_count"]);
  text(source.label, 120); text(source.file_name, 255);
  if (!["RESEARCH", "RECORDED"].includes(source.kind as string) || /[\\/]/.test(source.file_name)
    || source.file_name === "." || source.file_name.includes("..")
    || typeof source.sha256 !== "string" || !/^[a-f0-9]{64}$/.test(source.sha256)) invalid();
  integer(source.byte_size, SENTRY_MAX_BYTES); integer(source.raw_count, SENTRY_MAX_ROWS); integer(source.duplicate_count, SENTRY_MAX_ROWS);
  if (source.raw_count !== observations.length + source.duplicate_count) invalid();
  let latest: string | null = null;
  for (const entry of observations) {
    if (nanos(entry.observed_at) > nanos(item.checked_at) + 5_000_000_000n) invalid();
    if (latest === null || nanos(entry.observed_at) > nanos(latest)) latest = entry.observed_at;
  }
  if (latest === null) {
    if (source.latest_observed_at !== null) invalid();
  } else {
    timestamp(source.latest_observed_at, true);
    if (nanos(source.latest_observed_at) !== nanos(latest)) invalid();
  }
  return item as unknown as SentryFeed;
}

/** Fixed same-origin GET; no arbitrary paths, credentials, mutations, or synthetic fallback. */
export async function loadSentryFeed({ signal }: { signal?: AbortSignal } = {}): Promise<SentryFeed> {
  const response = await fetch(SENTRY_FEED_URL, { method: "GET", signal, cache: "no-store", redirect: "error", credentials: "same-origin", headers: { Accept: "application/json" } });
  const length = response.headers.get("content-length");
  if (!response.ok || !/^application\/json(?:;|$)/i.test(response.headers.get("content-type") ?? "")
    || (length !== null && (!/^\d+$/.test(length) || Number(length) > SENTRY_MAX_BYTES))) {
    await response.body?.cancel().catch(() => {});
    return invalid();
  }
  if (!response.body) return invalid();
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let size = 0; let body = "";
  try {
    while (true) {
      if (signal?.aborted) return invalid();
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > SENTRY_MAX_BYTES) return invalid();
      body += decoder.decode(value, { stream: true });
    }
    body += decoder.decode();
    if (signal?.aborted) return invalid();
    return validateSentryFeed(JSON.parse(body));
  } catch { return invalid(); }
  finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}

/** Check the reader receipt ordering only: older research observations remain explicitly old. */
export function sentryFeedIsOlder(next: SentryFeed, previous: SentryFeed): boolean {
  return nanos(next.checked_at) < nanos(previous.checked_at);
}
