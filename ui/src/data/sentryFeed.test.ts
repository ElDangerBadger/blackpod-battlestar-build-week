import { afterEach, describe, expect, it, vi } from "vitest";
import type { SentryFeed, SentrySnapshot } from "../contracts/sentry";
import { loadSentryFeed, SENTRY_FEED_URL, SENTRY_MAX_BYTES, sentryFeedIsOlder, validateSentryFeed } from "./sentryFeed";

function observation(): SentrySnapshot {
  return { schema_version: "microcap_sentry.snapshot.v1", event_id: "synthetic-event-1", symbol: "SYNBRK",
    observed_at: "2026-07-15T14:10:00Z", classification: "CONFIRMED_MOMENTUM",
    eligibility: { eligible: true, reasons: ["Recorded eligibility result."], warnings: [], missing_fields: [] },
    features: { price_change_1m_pct: 5, price_change_5m_pct: 22, price_change_15m_pct: null,
      distance_from_session_high_pct: -0.8, distance_from_vwap_pct: 10.9, new_session_high: true,
      volume_ratio_1m: 5, volume_ratio_5m: 5, volume_acceleration: 5, cumulative_relative_volume: 2.8,
      spread_pct: 1.6, dollar_volume: 6100, quote_imbalance: 0.6, executable_liquidity_warning: true,
      warnings: ["INSUFFICIENT_HISTORY_15M"], missing_data_fields: ["price_change_15m_pct"] },
    powder_keg: { total_score: 77.5, contributions: [{ factor: "low_float", contribution: 11.7,
      observed_value: 8000000, threshold: "secondary tier", reason: "Recorded source reason." }], reasons: [], warnings: [], missing_data_fields: [] },
    ignition: { total_score: 95, contributions: [], reasons: [], warnings: [], missing_data_fields: [] },
    continuation: { total_score: null, contributions: [], reasons: [], warnings: [], missing_data_fields: ["prior context"] },
    symbol_profile: null, catalysts: [], news_events: [], filing_events: [], halt_events: [],
    risks: ["executable-liquidity warning"], missing_information: [], reasons: [], observation_only: true, order_submission_enabled: false };
}
function feed(): SentryFeed {
  return { schema_version: "blackpod.sentry_feed.v1", status: "READY", checked_at: "2026-09-16T20:00:00Z",
    message: "Verified research archive.", source: { label: "Historical synthetic research", kind: "RESEARCH",
      file_name: "2026-07-15.jsonl", sha256: "a".repeat(64), byte_size: 4000, latest_observed_at: "2026-07-15T14:10:00Z",
      raw_count: 1, duplicate_count: 0 }, observations: [observation()] };
}
const now = Date.parse("2026-09-16T20:00:00Z");
const response = (body: unknown, headers: HeadersInit = {}) => new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json", ...headers } });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("canonical Sentry feed validation", () => {
  it("preserves historical scores, absent configured weights, nullable continuation and research provenance exactly", () => {
    const original = feed(); const frozen = JSON.stringify(original);
    expect(validateSentryFeed(original, now)).toBe(original);
    expect(JSON.stringify(original)).toBe(frozen);
    expect(original.observations[0].powder_keg.contributions[0]).not.toHaveProperty("configured_weight");
  });

  it.each(["NOT_CONFIGURED", "UNAVAILABLE"] as const)("accepts empty %s without inventing observations", (status) => {
    expect(validateSentryFeed({ ...feed(), status, source: null, observations: [] }, now).status).toBe(status);
  });

  it.each([
    ["unknown envelope field", (item: SentryFeed) => Object.assign(item, { trades: [] })],
    ["unknown status", (item: SentryFeed) => Object.assign(item, { status: "LIVE" })],
    ["invalid time", (item: SentryFeed) => { item.checked_at = "2026-02-30T20:00:00Z"; }],
    ["future receipt", (item: SentryFeed) => { item.checked_at = "2026-09-16T20:00:06Z"; }],
    ["naive timestamp", (item: SentryFeed) => { item.observations[0].observed_at = "2026-07-15T14:10:00"; }],
    ["future observation", (item: SentryFeed) => { item.observations[0].observed_at = "2026-09-17T14:10:00Z"; }],
    ["wrong source hash", (item: SentryFeed) => { item.source!.sha256 = "bad"; }],
    ["unsafe path", (item: SentryFeed) => { item.source!.file_name = "../archive.jsonl"; }],
    ["ambiguous basename", (item: SentryFeed) => { item.source!.file_name = "archive..jsonl"; }],
    ["source too large", (item: SentryFeed) => { item.source!.byte_size = SENTRY_MAX_BYTES + 1; }],
    ["too many rows", (item: SentryFeed) => { item.source!.raw_count = 1001; }],
    ["incoherent counts", (item: SentryFeed) => { item.source!.duplicate_count = 1; }],
    ["fractional count", (item: SentryFeed) => { item.source!.raw_count = 1.5; }],
    ["unsafe integer", (item: SentryFeed) => { item.observations[0].features.dollar_volume = Number.MAX_SAFE_INTEGER + 1; }],
    ["nonfinite feature", (item: SentryFeed) => { item.observations[0].features.dollar_volume = Infinity; }],
    ["NaN score", (item: SentryFeed) => { item.observations[0].ignition.total_score = NaN; }],
    ["out of range score", (item: SentryFeed) => { item.observations[0].ignition.total_score = 101; }],
    ["unknown classification", (item: SentryFeed) => Object.assign(item.observations[0], { classification: "BUY" })],
    ["missing explicit safety", (item: SentryFeed) => { Reflect.deleteProperty(item.observations[0], "observation_only"); }],
    ["execution enabled", (item: SentryFeed) => Object.assign(item.observations[0], { order_submission_enabled: true })],
    ["duplicate event identity", (item: SentryFeed) => { item.observations.push(observation()); item.source!.raw_count = 2; }],
    ["latest date differs", (item: SentryFeed) => { item.source!.latest_observed_at = "2026-07-15T15:10:00Z"; }],
    ["nested unknown field", (item: SentryFeed) => Object.assign(item.observations[0].features, { recommendation: "BUY" })],
    ["long text", (item: SentryFeed) => { item.observations[0].reasons = ["x".repeat(4001)]; }],
    ["cross-symbol catalyst", (item: SentryFeed) => { item.observations[0].catalysts = [{ symbol: "OTHER", timestamp: "2026-07-15T14:00:00Z", catalyst_type: "NEWS", summary: "", material: null, source_event_id: null, confidence: null }]; }],
    ["non-ready observations", (item: SentryFeed) => { item.status = "UNAVAILABLE"; }],
  ] as const)("rejects %s", (_description, mutate) => {
    const item = feed(); mutate(item); expect(() => validateSentryFeed(item, now)).toThrow(/unavailable or invalid/);
  });

  it("accepts deduplicated rows and checks submillisecond latest dates", () => {
    const item = feed(); item.source!.raw_count = 3; item.source!.duplicate_count = 2;
    item.observations[0].observed_at = "2026-07-15T14:10:00.000000001Z";
    item.source!.latest_observed_at = item.observations[0].observed_at;
    expect(validateSentryFeed(item, now)).toBe(item);
    item.source!.latest_observed_at = "2026-07-15T14:10:00.000000002Z";
    expect(() => validateSentryFeed(item, now)).toThrow();
  });

  it("preserves aware-offset canonical timestamps while matching normalized UTC source metadata", () => {
    const item = feed();
    item.observations[0].observed_at = "2026-07-15T09:10:00.000001-05:00";
    item.source!.latest_observed_at = "2026-07-15T14:10:00.000001Z";
    item.observations[0].catalysts = [{ symbol: "SYNBRK", timestamp: "2026-07-15T09:00:00-05:00", catalyst_type: "NEWS",
      summary: "Recorded context", source_event_id: null, material: null, confidence: null }];
    expect(validateSentryFeed(item, now)).toBe(item);
    expect(item.observations[0].observed_at).toBe("2026-07-15T09:10:00.000001-05:00");
    item.observations[0].observed_at = "2026-02-30T09:10:00-05:00";
    expect(() => validateSentryFeed(item, now)).toThrow();
  });

  it("rejects non-UTC receipt metadata even when offset-equivalent", () => {
    const item = feed(); item.checked_at = "2026-09-16T15:00:00-05:00";
    expect(() => validateSentryFeed(item, now)).toThrow();
    item.checked_at = "2026-09-16T20:00:00Z"; item.source!.latest_observed_at = "2026-07-15T09:10:00-05:00";
    expect(() => validateSentryFeed(item, now)).toThrow();
  });

  it("requires null latest timestamp for an empty verified archive", () => {
    const item = feed(); item.observations = []; item.source!.raw_count = 0; item.source!.latest_observed_at = null;
    expect(validateSentryFeed(item, now)).toBe(item);
    item.source!.latest_observed_at = "2026-07-15T14:10:00Z";
    expect(() => validateSentryFeed(item, now)).toThrow();
  });

  it("compares receipt order without replacing old observation dates", () => {
    const before = feed(); const after = feed();
    before.checked_at = "2026-09-16T20:00:00.000000001Z";
    after.checked_at = "2026-09-16T20:00:00.000000002Z";
    expect(sentryFeedIsOlder(before, after)).toBe(true);
    expect(sentryFeedIsOlder(after, before)).toBe(false);
  });
});

describe("bounded read-only Sentry request", () => {
  it("uses one fixed same-origin GET and preserves historical research records", async () => {
    vi.spyOn(Date, "now").mockReturnValue(now);
    const fetcher = vi.fn().mockResolvedValue(response(feed())); vi.stubGlobal("fetch", fetcher);
    const controller = new AbortController();
    expect(await loadSentryFeed({ signal: controller.signal })).toEqual(feed());
    expect(fetcher).toHaveBeenCalledWith(SENTRY_FEED_URL, expect.objectContaining({ method: "GET", redirect: "error", cache: "no-store", signal: controller.signal }));
  });

  it.each([
    ["oversized declared response", () => response(feed(), { "content-length": String(SENTRY_MAX_BYTES + 1) })],
    ["HTML response", () => new Response("<html>", { headers: { "content-type": "text/html" } })],
    ["server failure", () => new Response("private details", { status: 500, headers: { "content-type": "application/json" } })],
    ["malformed JSON", () => new Response("{", { headers: { "content-type": "application/json" } })],
    ["oversized streamed response", () => new Response(" ".repeat(SENTRY_MAX_BYTES + 1), { headers: { "content-type": "application/json" } })],
    ["invalid UTF8", () => new Response(new Uint8Array([0xc3, 0x28]), { headers: { "content-type": "application/json" } })],
  ] as const)("rejects %s with no payload disclosure", async (_description, create) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(create()));
    await expect(loadSentryFeed()).rejects.toThrow("Sentry archive response is unavailable or invalid.");
  });

  it("discards an aborted request before parsing", async () => {
    const controller = new AbortController(); controller.abort();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(feed())));
    await expect(loadSentryFeed({ signal: controller.signal })).rejects.toThrow();
  });

  it("cancels a rejected response body without downloading it", async () => {
    const cancel = vi.fn();
    const stream = new ReadableStream<Uint8Array>({ cancel });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(stream, { headers: {
      "content-type": "application/json", "content-length": String(SENTRY_MAX_BYTES + 1),
    } })));
    await expect(loadSentryFeed()).rejects.toThrow();
    expect(cancel).toHaveBeenCalledTimes(1);
  });
});
