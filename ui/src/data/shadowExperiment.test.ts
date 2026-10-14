import { afterEach, describe, expect, it, vi } from "vitest";
import { createShadowExperimentFixture } from "../test/shadowExperimentFixture";
import { loadShadowExperiment, SHADOW_EXPERIMENT_MAX_BYTES, SHADOW_EXPERIMENT_URL, validateShadowExperiment } from "./shadowExperiment";

const now = Date.parse("2026-10-21T06:00:00Z");
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
describe("shadow experiment presentation contract", () => {
  it.each([false, true])("preserves complete protocol, predictions and absent metrics (rows=%s)", (rows) => {
    const value = createShadowExperimentFixture(rows), before = JSON.stringify(value);
    expect(validateShadowExperiment(value, now)).toBe(value);
    expect(JSON.stringify(value)).toBe(before);
  });
  it("retains long exact decimal results while display rounding stays separate", () => {
    const value = createShadowExperimentFixture(true);
    value.experiment!.summary.mean_gross_return = "0." + "0".repeat(30) + "123456789".repeat(7);
    expect(validateShadowExperiment(value, now)).toBe(value);
  });
  const mutations: [string, (value: ReturnType<typeof createShadowExperimentFixture>) => void][] = [
    ["execution authority", (v) => Object.assign(v.experiment!.authority, { execution_enabled: true })],
    ["auto trading", (v) => Object.assign(v.experiment!, { auto_trading_enabled: true })],
    ["activated protocol", (v) => Object.assign(v.experiment!.protocol, { execution_status: "EXECUTED" })],
    ["invented net result", (v) => Object.assign(v.experiment!.summary, { net_return: "0.1" })],
    ["economic promotion", (v) => Object.assign(v.experiment!.summary, { economic_support: "SUPPORTED" })],
    ["changed method", (v) => v.experiment!.protocol.method_version = "unknown"],
    ["changed hypothesis", (v) => v.experiment!.protocol.original_hypothesis_id = "continuation"],
    ["future reader", (v) => v.checked_at = "2099-01-01T00:00:00Z"],
    ["future capture", (v) => v.experiment!.latest_captured_at = "2099-01-01T00:00:00Z"],
    ["invalid date", (v) => v.experiment!.protocol.frozen_at = "2026-02-30T00:00:00Z"],
    ["wrong universe", (v) => Object.assign(v.experiment!.protocol, { universe: ["QQQ", "AAPL"] })],
    ["missing schedule", (v) => v.experiment!.protocol.context_sessions.pop()],
    ["changed minimum", (v) => v.experiment!.protocol.criteria.minimum_observed_candidates = 1],
    ["source traversal", (v) => v.experiment!.protocol.hypothesis_evidence.path = "../source"],
    ["duplicate prediction", (v) => v.experiment!.predictions.push(v.experiment!.predictions[0])],
    ["unlinked outcome", (v) => v.experiment!.outcomes[0].prediction_id = "missing"],
    ["cross-symbol outcome", (v) => v.experiment!.outcomes[0].symbol = "SPY"],
    ["duplicate outcome", (v) => v.experiment!.outcomes.push(v.experiment!.outcomes[0])],
    ["nonfinite return", (v) => v.experiment!.outcomes[0].candidate_gross_return = "NaN"],
    ["boolean count", (v) => Object.assign(v.experiment!.summary, { observed_outcome_count: false })],
    ["invented row count", (v) => v.experiment!.summary.recorded_prediction_count = 3],
    ["unknown field", (v) => Object.assign(v, { orders: [] })],
  ];
  it.each(mutations)("rejects %s", (_name, mutate) => {
    const value = createShadowExperimentFixture(true); mutate(value);
    expect(() => validateShadowExperiment(value, now)).toThrow();
  });
  it.each(["NOT_CONFIGURED", "UNAVAILABLE"] as const)("accepts %s only without experiment data", (status) => {
    const value = { ...createShadowExperimentFixture(), status, experiment: null };
    expect(validateShadowExperiment(value, now)).toBe(value);
    expect(() => validateShadowExperiment({ ...value, experiment: createShadowExperimentFixture().experiment }, now)).toThrow();
  });
  it("reads the one bounded GET endpoint with no mutation or provider action", async () => {
    vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(now);
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(createShadowExperimentFixture(true)), { headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetch);
    expect((await loadShadowExperiment()).status).toBe("READY");
    expect(fetch).toHaveBeenCalledOnce();
    expect(fetch).toHaveBeenCalledWith(SHADOW_EXPERIMENT_URL, expect.objectContaining({ method: "GET", redirect: "error", cache: "no-store", credentials: "same-origin" }));
  });
  it.each(["html", "oversize-header", "oversize-stream", "failed", "malformed"])("rejects %s transport", async (kind) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(kind === "oversize-stream" ? "x".repeat(SHADOW_EXPERIMENT_MAX_BYTES + 1) : "invalid", {
      status: kind === "failed" ? 503 : 200, headers: { "content-type": kind === "html" ? "text/html" : "application/json", ...(kind === "oversize-header" ? { "content-length": String(SHADOW_EXPERIMENT_MAX_BYTES + 1) } : {}) },
    })));
    await expect(loadShadowExperiment()).rejects.toThrow();
  });
});
