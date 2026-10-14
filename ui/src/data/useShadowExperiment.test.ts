import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createShadowExperimentFixture } from "../test/shadowExperimentFixture";
import { loadShadowExperiment } from "./shadowExperiment";
import { SHADOW_EXPERIMENT_TIMEOUT_MS, useShadowExperiment } from "./useShadowExperiment";

vi.mock("./shadowExperiment", () => ({ loadShadowExperiment: vi.fn() }));
const loader = vi.mocked(loadShadowExperiment);
const flush = async () => { await act(async () => { await Promise.resolve(); }); };
describe("shadow experiment read lifecycle", () => {
  beforeEach(() => {
    vi.useFakeTimers(); vi.setSystemTime(new Date("2026-10-21T06:00:00Z"));
    loader.mockReset().mockResolvedValue(createShadowExperimentFixture());
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });
  it("reads once on open and once per manual refresh, with no timer-driven collection", async () => {
    const { result } = renderHook(() => useShadowExperiment({ enabled: true }));
    await flush(); expect(result.current.status).toBe("READY");
    await act(() => vi.advanceTimersByTimeAsync(3_600_000)); expect(loader).toHaveBeenCalledOnce();
    act(() => result.current.refresh()); await flush(); expect(loader).toHaveBeenCalledTimes(2);
  });
  it("does not read while disabled, including manual refresh", async () => {
    const { result } = renderHook(() => useShadowExperiment({ enabled: false }));
    act(() => result.current.refresh()); await flush();
    expect(loader).not.toHaveBeenCalled(); expect(result.current.feed).toBeNull();
  });
  it.each(["NOT_CONFIGURED", "UNAVAILABLE"] as const)("clears prior rows on %s instead of showing them as current", async (status) => {
    const { result } = renderHook(() => useShadowExperiment({ enabled: true })); await flush();
    loader.mockResolvedValue({ ...createShadowExperimentFixture(), status, experiment: null, message: "Unavailable." });
    act(() => result.current.refresh()); await flush();
    expect(result.current.status).toBe(status); expect(result.current.feed).toBeNull();
  });
  it("hides native errors and clears prior data after failure, then recovers", async () => {
    const { result } = renderHook(() => useShadowExperiment({ enabled: true })); await flush();
    loader.mockRejectedValueOnce(new Error("/private/secret")); act(() => result.current.refresh()); await flush();
    expect(result.current.status).toBe("UNAVAILABLE"); expect(result.current.feed).toBeNull(); expect(result.current.message).not.toContain("private");
    act(() => result.current.refresh()); await flush(); expect(result.current.status).toBe("READY");
  });
  it("rejects an out-of-order reader receipt", async () => {
    const { result } = renderHook(() => useShadowExperiment({ enabled: true })); await flush();
    loader.mockResolvedValue({ ...createShadowExperimentFixture(), checked_at: "2026-10-20T05:00:00Z" });
    act(() => result.current.refresh()); await flush(); expect(result.current.status).toBe("UNAVAILABLE");
  });
  it("times out a hung read and ignores late resolution without automatic retry", async () => {
    let finish!: (value: ReturnType<typeof createShadowExperimentFixture>) => void;
    loader.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const { result } = renderHook(() => useShadowExperiment({ enabled: true }));
    await act(() => vi.advanceTimersByTimeAsync(SHADOW_EXPERIMENT_TIMEOUT_MS));
    expect(result.current.status).toBe("UNAVAILABLE"); expect(loader.mock.calls[0][0]?.signal?.aborted).toBe(true);
    finish(createShadowExperimentFixture()); await flush(); expect(result.current.feed).toBeNull();
    await act(() => vi.advanceTimersByTimeAsync(3_600_000)); expect(loader).toHaveBeenCalledOnce();
  });
  it("aborts on close and prevents late data from crossing a reopen", async () => {
    let finish!: (value: ReturnType<typeof createShadowExperimentFixture>) => void;
    loader.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const { result, rerender } = renderHook((props) => useShadowExperiment(props), { initialProps: { enabled: true } });
    const signal = loader.mock.calls[0][0]?.signal; rerender({ enabled: false }); expect(signal?.aborted).toBe(true);
    rerender({ enabled: true }); await flush(); expect(result.current.status).toBe("READY");
    finish({ ...createShadowExperimentFixture(), checked_at: "2026-10-21T05:30:00Z" }); await flush();
    expect(result.current.feed?.checked_at).toBe("2026-10-21T05:00:00Z");
  });
  it("pauses when hidden and does not fetch merely on returning visible", async () => {
    const visibility = vi.spyOn(document, "visibilityState", "get");
    const { result } = renderHook(() => useShadowExperiment({ enabled: true })); await flush();
    visibility.mockReturnValue("hidden"); act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(result.current.status).toBe("DISABLED"); expect(result.current.feed).toBeNull();
    visibility.mockReturnValue("visible"); act(() => document.dispatchEvent(new Event("visibilitychange"))); await flush();
    expect(loader).toHaveBeenCalledOnce(); act(() => result.current.refresh()); await flush(); expect(loader).toHaveBeenCalledTimes(2);
  });
});
