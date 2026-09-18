import { afterEach, describe, expect, it, vi } from "vitest";
import { createSentryScanFixture } from "../test/sentryScanFixture";
import { loadSentryScanFeed, SENTRY_SCAN_MAX_BYTES, SENTRY_SCAN_URL, validateSentryScanFeed } from "./sentryScanFeed";

const now = Date.parse("2026-09-18T08:00:00Z");
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
describe("scan receipt presentation contract", () => {
  it("preserves canonical order, reasons and values without scoring", () => {
    const value = createSentryScanFixture(), before = JSON.stringify(value);
    expect(validateSentryScanFeed(value, now)).toBe(value);
    expect(JSON.stringify(value)).toBe(before);
  });
  const mutations: [string, (v: ReturnType<typeof createSentryScanFixture>) => void][] = [
    ["orders", (v) => { Object.assign(v, { order_submission_enabled: true }); }],
    ["not observation only", (v) => { Object.assign(v, { observation_only: false }); }],
    ["current attention", (v) => { Object.assign(v, { current_attention_published: true }); }],
    ["wrong kind", (v) => { Object.assign(v.scan!, { scan_kind: "LIVE" }); }],
    ["declared evidence verified", (v) => { Object.assign(v.source!, { declared_evidence_reverified: true }); }],
    ["production profile", (v) => { Object.assign(v.scan!.profile_statuses, { ETF: "PRODUCTION_READY" }); }],
    ["future check", (v) => { v.checked_at = "2027-01-01T00:00:00Z"; }],
    ["future scan", (v) => { v.scan!.as_of = "2026-09-18T08:01:00Z"; }],
    ["incomplete session", (v) => { v.scan!.session_date = "2026-09-18"; }],
    ["invalid calendar", (v) => { v.scan!.as_of = "2026-02-30T00:00:00Z"; }],
    ["NaN", (v) => { v.scan!.windows[0].selected[0].percentile = NaN; }],
    ["infinite capacity", (v) => { v.scan!.configuration.capacity = Infinity; }],
    ["unsafe count", (v) => { v.scan!.population.requested_count = Number.MAX_SAFE_INTEGER + 1; }],
    ["duplicate population", (v) => { v.scan!.population.requested.push("AAPL"); }],
    ["failed observed overlap", (v) => { v.scan!.population.failed = ["AAPL"]; }],
    ["wrong count", (v) => { v.scan!.population.failed_count = 0; }],
    ["missing row", (v) => { v.scan!.symbols.pop(); }],
    ["no failure reason", (v) => { v.scan!.symbols[1].reasons = []; }],
    ["failed selected", (v) => { v.scan!.windows[0].selected[0].symbol = "IWM"; }],
    ["duplicate window", (v) => { v.scan!.windows[1].lookback = 20; }],
    ["duplicate selected and excluded", (v) => { v.scan!.windows[0].excluded = [...v.scan!.windows[0].selected]; }],
    ["padding capacity", (v) => { v.scan!.windows[0].capacity_remaining = 0; }],
    ["profile capacity", (v) => { v.scan!.configuration.per_profile_capacity.GENERAL_EQUITY = 0; }],
    ["below threshold selected", (v) => { v.scan!.windows[0].selected[0].percentile = .94; }],
    ["missing percentile selected", (v) => { v.scan!.windows[0].selected[0].percentile = null; }],
    ["unknown calibration", (v) => { v.scan!.windows[0].selected[0].calibration_id = "unknown"; }],
    ["noneligible winner", (v) => { v.scan!.windows[0].excluded[0].winning_assessment_id = "fake"; }],
    ["wrong eligible count", (v) => { v.scan!.windows[0].eligible_candidate_count = 2; }],
    ["changed fixed threshold", (v) => { v.scan!.configuration.minimum_percentile = .9; }],
    ["observed exclusion reasons", (v) => { v.scan!.symbols[0].reasons = ["FAILED"]; }],
    ["same-day observed capture", (v) => { v.scan!.symbols[0].history!.captured_at = "2026-09-17T23:59:59Z"; }],
    ["stale observed history", (v) => { v.scan!.symbols[0].history!.last_session = "2026-09-16"; }],
    ["short observed history", (v) => { v.scan!.symbols[0].history!.row_count = 65; }],
    ["future capture", (v) => { v.scan!.symbols[0].history!.captured_at = "2026-09-18T06:01:00Z"; }],
    ["unusable observed history", (v) => { v.scan!.symbols[0].history_validation!.research_usable = false; }],
    ["path traversal", (v) => { v.source!.file_name = "../scan.json"; }],
    ["oversize receipt", (v) => { v.source!.byte_size = 16 * 1024 * 1024 + 1; }],
    ["unknown key", (v) => { Object.assign(v, { broker: true }); }],
  ];
  it.each(mutations)("rejects %s", (_name, mutate) => {
    const value = createSentryScanFixture(); mutate(value);
    expect(() => validateSentryScanFeed(value, now)).toThrow();
  });
  it("keeps malformed excluded-history evidence without rejecting healthy symbols", () => {
    const value = createSentryScanFixture();
    value.scan!.symbols[1].history = { ...value.scan!.symbols[0].history!, first_session: null, last_session: null, row_count: 0 };
    expect(validateSentryScanFeed(value, now)).toBe(value);
  });
  it("accepts all-failed input and empty unpadded selections", () => {
    const value = createSentryScanFixture(), scan = value.scan!;
    scan.population.observed = []; scan.population.observed_count = 0;
    scan.population.failed = [...scan.population.requested]; scan.population.failed_count = 3;
    scan.symbols.forEach((row) => { row.status = "EXCLUDED"; row.reasons = ["INVALID_HISTORY"]; });
    scan.windows.forEach((window) => { window.candidate_count = 0; window.eligible_candidate_count = 0; window.selected = []; window.excluded = []; window.capacity_remaining = 6; });
    expect(validateSentryScanFeed(value, now)).toBe(value);
  });
  it.each(["NOT_CONFIGURED", "UNAVAILABLE"] as const)("accepts %s only without attached evidence", (status) => {
    const value = { ...createSentryScanFixture(), status, source: null, scan: null };
    expect(validateSentryScanFeed(value, now)).toBe(value);
    expect(() => validateSentryScanFeed({ ...value, scan: createSentryScanFixture().scan }, now)).toThrow();
  });
  it("reads only the fixed bounded same-origin endpoint", async () => {
    vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(now);
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(createSentryScanFixture()), { headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetch);
    expect((await loadSentryScanFeed()).status).toBe("READY");
    expect(fetch).toHaveBeenCalledWith(SENTRY_SCAN_URL, expect.objectContaining({ method: "GET", redirect: "error", cache: "no-store", credentials: "same-origin" }));
  });
  it.each(["html", "oversize-header", "oversize-stream", "failed", "malformed"])("rejects %s transport", async (kind) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(kind === "oversize-stream" ? "x".repeat(SENTRY_SCAN_MAX_BYTES + 1) : "invalid", {
      status: kind === "failed" ? 503 : 200, headers: { "content-type": kind === "html" ? "text/html" : "application/json", ...(kind === "oversize-header" ? { "content-length": String(SENTRY_SCAN_MAX_BYTES + 1) } : {}) },
    })));
    await expect(loadSentryScanFeed()).rejects.toThrow();
  });
});
