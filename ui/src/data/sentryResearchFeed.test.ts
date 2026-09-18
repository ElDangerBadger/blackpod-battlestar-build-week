import { afterEach, describe, expect, it, vi } from "vitest";
import { createSentryResearchFixture } from "../test/sentryResearchFixture";
import { loadSentryResearchFeed, SENTRY_RESEARCH_MAX_BYTES, SENTRY_RESEARCH_URL, validateSentryResearchFeed } from "./sentryResearchFeed";

const now = Date.parse("2026-09-18T06:00:00Z");
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
describe("research checkpoint contract", () => {
  it("preserves supplied facts without transforming or recomputing", () => {
    const value = createSentryResearchFixture();
    const original = JSON.stringify(value);
    expect(validateSentryResearchFeed(value, now)).toBe(value);
    expect(JSON.stringify(value)).toBe(original);
  });
  it.each([
    ["orders", (v: ReturnType<typeof createSentryResearchFixture>) => { Object.assign(v, { order_submission_enabled: true }); }],
    ["published attention", (v: ReturnType<typeof createSentryResearchFixture>) => { Object.assign(v, { current_attention_published: true }); }],
    ["synthetic kind", (v: ReturnType<typeof createSentryResearchFixture>) => { Object.assign(v.source!, { kind: "RESEARCH" }); }],
    ["upstream reverified", (v: ReturnType<typeof createSentryResearchFixture>) => { Object.assign(v.source!, { upstream_artifacts_reverified: true }); }],
    ["future check", (v: ReturnType<typeof createSentryResearchFixture>) => { v.checked_at = "2027-01-01T00:00:00Z"; }],
    ["invalid calendar", (v: ReturnType<typeof createSentryResearchFixture>) => { v.source!.archive_as_of = "2026-02-30T00:00:00Z"; }],
    ["archive after reader", (v: ReturnType<typeof createSentryResearchFixture>) => { v.source!.archive_as_of = "2026-09-18T05:01:00Z"; }],
    ["NaN", (v: ReturnType<typeof createSentryResearchFixture>) => { v.study!.policies[0].mean_overlap = NaN; }],
    ["infinity", (v: ReturnType<typeof createSentryResearchFixture>) => { v.study!.policies[0].windows[0].mean_selected = Infinity; }],
    ["duplicate cohort", (v: ReturnType<typeof createSentryResearchFixture>) => { v.study!.cohort[0] = v.study!.cohort[1]; }],
    ["missing symbol", (v: ReturnType<typeof createSentryResearchFixture>) => { v.study!.cohort.pop(); }],
    ["unknown contributor", (v: ReturnType<typeof createSentryResearchFixture>) => { v.study!.policies[0].windows[0].top_symbols[0].symbol = "UNKNOWN"; }],
    ["duplicate window", (v: ReturnType<typeof createSentryResearchFixture>) => { v.study!.policies[0].windows[1].lookback = 20; }],
    ["altered criterion", (v: ReturnType<typeof createSentryResearchFixture>) => { v.study!.criteria.mean_new_names_limit = 3; }],
    ["incorrect count", (v: ReturnType<typeof createSentryResearchFixture>) => { v.prospective!.warmup.ready_symbols = 24; }],
    ["successful warmup", (v: ReturnType<typeof createSentryResearchFixture>) => { v.prospective!.warmup.complete_cohort_sealed = true; }],
    ["completed prospective", (v: ReturnType<typeof createSentryResearchFixture>) => { v.prospective!.completed_sessions = 1; }],
    ["pass narrative", (v: ReturnType<typeof createSentryResearchFixture>) => { v.study!.all_policies_failed = false; }],
    ["not capped", (v: ReturnType<typeof createSentryResearchFixture>) => { v.study!.policies[2].capped_by_construction = false; }],
    ["path traversal", (v: ReturnType<typeof createSentryResearchFixture>) => { v.source!.files[0].file_name = "../secret"; }],
    ["unknown contract key", (v: ReturnType<typeof createSentryResearchFixture>) => { Object.assign(v, { broker: true }); }],
  ])("rejects %s", (_name, mutate) => {
    const value = createSentryResearchFixture(); (mutate as (v: typeof value) => void)(value);
    expect(() => validateSentryResearchFeed(value, now)).toThrow();
  });
  it.each(["NOT_CONFIGURED", "UNAVAILABLE"] as const)("supports %s only without attached evidence", (status) => {
    const value = { ...createSentryResearchFixture(), status, source: null, study: null, prospective: null };
    expect(validateSentryResearchFeed(value, now)).toBe(value);
    expect(() => validateSentryResearchFeed({ ...value, study: createSentryResearchFixture().study }, now)).toThrow();
  });
  it("uses only a bounded same-origin GET without queries or mutation", async () => {
    vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(now);
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(createSentryResearchFixture()), { headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetch);
    expect((await loadSentryResearchFeed()).status).toBe("READY");
    expect(fetch).toHaveBeenCalledWith(SENTRY_RESEARCH_URL, expect.objectContaining({ method: "GET", redirect: "error", cache: "no-store" }));
  });
  it.each(["html", "oversize-header", "oversize-stream", "failed", "malformed"])("rejects %s response", async (kind) => {
    const response = new Response(kind === "oversize-stream" ? "x".repeat(SENTRY_RESEARCH_MAX_BYTES + 1) : "not-json", {
      status: kind === "failed" ? 503 : 200,
      headers: { "content-type": kind === "html" ? "text/html" : "application/json", ...(kind === "oversize-header" ? { "content-length": String(SENTRY_RESEARCH_MAX_BYTES + 1) } : {}) },
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    await expect(loadSentryResearchFeed()).rejects.toThrow();
  });
});
