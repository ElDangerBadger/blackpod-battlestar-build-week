import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SentryResearchFeed } from "../contracts/sentryResearch";
import { createSentryResearchFixture } from "../test/sentryResearchFixture";
import { loadSentryResearchFeed } from "./sentryResearchFeed";
import { SENTRY_RESEARCH_TIMEOUT_MS, useSentryResearchFeed } from "./useSentryResearchFeed";

vi.mock("./sentryResearchFeed", () => ({ loadSentryResearchFeed: vi.fn() }));
const loader = vi.mocked(loadSentryResearchFeed);
const flush = async () => { await act(async () => { await Promise.resolve(); }); };
const unavailable = (status: "NOT_CONFIGURED" | "UNAVAILABLE"): SentryResearchFeed => ({
  ...createSentryResearchFixture(), status, source: null, study: null, prospective: null,
  message: "Research archive unavailable.",
});

describe("Sentry Research reader lifecycle", () => {
  beforeEach(() => {
    vi.useFakeTimers(); vi.setSystemTime(new Date("2026-09-18T06:00:00Z"));
    loader.mockReset().mockResolvedValue(createSentryResearchFixture());
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

  it("reads once on opening and once per manual refresh, without polling", async () => {
    const { result, unmount } = renderHook(() => useSentryResearchFeed({ enabled: true }));
    expect(result.current.status).toBe("LOADING");
    await flush();
    expect(result.current.status).toBe("READY");
    expect(result.current.feed?.source?.kind).toBe("FIXED_RESEARCH_CHECKPOINT");
    await act(() => vi.advanceTimersByTimeAsync(3_600_000));
    expect(loader).toHaveBeenCalledTimes(1);
    act(() => result.current.refresh()); await flush();
    expect(loader).toHaveBeenCalledTimes(2);
    unmount();
    await act(() => vi.advanceTimersByTimeAsync(3_600_000));
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it("never reads while disabled or replayed, including manual refresh", async () => {
    const { result } = renderHook(() => useSentryResearchFeed({ enabled: false }));
    act(() => result.current.refresh()); await flush();
    expect(result.current.status).toBe("DISABLED");
    expect(result.current.feed).toBeNull();
    expect(loader).not.toHaveBeenCalled();
  });

  it.each(["NOT_CONFIGURED", "UNAVAILABLE"] as const)("does not invent results for %s", async (status) => {
    loader.mockResolvedValue(unavailable(status));
    const { result } = renderHook(() => useSentryResearchFeed({ enabled: true }));
    await flush();
    expect(result.current.status).toBe(status);
    expect(result.current.feed).toBeNull();
  });

  it("retains last-good evidence on a failed refresh, hides raw errors, and recovers", async () => {
    const { result } = renderHook(() => useSentryResearchFeed({ enabled: true }));
    await flush(); const prior = result.current.feed;
    loader.mockRejectedValueOnce(new Error("private server details"));
    act(() => result.current.refresh()); await flush();
    expect(result.current.status).toBe("UNAVAILABLE");
    expect(result.current.feed).toBe(prior);
    expect(result.current.message).toContain("current availability is unconfirmed");
    expect(result.current.message).not.toContain("private");
    act(() => result.current.refresh()); await flush();
    expect(result.current.status).toBe("READY");
  });

  it.each(["NOT_CONFIGURED", "UNAVAILABLE"] as const)("retains old evidence with a distinct %s server status", async (status) => {
    const { result } = renderHook(() => useSentryResearchFeed({ enabled: true }));
    await flush(); const prior = result.current.feed;
    loader.mockResolvedValue(unavailable(status));
    act(() => result.current.refresh()); await flush();
    expect(result.current.status).toBe(status);
    expect(result.current.feed).toBe(prior);
    expect(result.current.message).toBe("Research archive unavailable.");
  });

  it("does not roll evidence back to an out-of-order reader receipt", async () => {
    const { result } = renderHook(() => useSentryResearchFeed({ enabled: true }));
    await flush(); const prior = result.current.feed;
    loader.mockResolvedValue({ ...createSentryResearchFixture(), checked_at: "2026-09-18T04:59:59Z" });
    act(() => result.current.refresh()); await flush();
    expect(result.current.status).toBe("UNAVAILABLE");
    expect(result.current.feed).toBe(prior);
  });

  it("bounds a hung read, aborts it, and ignores a late result without automatic retry", async () => {
    let resolveFirst!: (value: SentryResearchFeed) => void;
    loader.mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }));
    const { result } = renderHook(() => useSentryResearchFeed({ enabled: true }));
    await act(() => vi.advanceTimersByTimeAsync(SENTRY_RESEARCH_TIMEOUT_MS - 1));
    expect(result.current.status).toBe("LOADING");
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(result.current.status).toBe("UNAVAILABLE");
    expect(loader.mock.calls[0][0]?.signal?.aborted).toBe(true);
    resolveFirst(createSentryResearchFixture()); await flush();
    expect(result.current.feed).toBeNull();
    await act(() => vi.advanceTimersByTimeAsync(3_600_000));
    expect(loader).toHaveBeenCalledTimes(1);
  });

  it("aborts on close and keeps a late result from crossing a reopen", async () => {
    let resolveFirst!: (value: SentryResearchFeed) => void;
    loader.mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }));
    const { result, rerender } = renderHook((props) => useSentryResearchFeed(props), { initialProps: { enabled: true } });
    const signal = loader.mock.calls[0][0]?.signal;
    rerender({ enabled: false });
    expect(signal?.aborted).toBe(true);
    rerender({ enabled: true }); await flush();
    expect(result.current.status).toBe("READY");
    resolveFirst({ ...createSentryResearchFixture(), checked_at: "2026-09-18T05:30:00Z" }); await flush();
    expect(result.current.feed?.checked_at).toBe("2026-09-18T05:00:00Z");
  });

  it("pauses and aborts when hidden; returning visible alone does not fetch", async () => {
    const visibility = vi.spyOn(document, "visibilityState", "get");
    const { result } = renderHook(() => useSentryResearchFeed({ enabled: true }));
    await flush(); const prior = result.current.feed;
    visibility.mockReturnValue("hidden");
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(result.current.status).toBe("DISABLED");
    expect(result.current.feed).toBe(prior);
    expect(loader.mock.calls[0][0]?.signal?.aborted).toBe(true);
    visibility.mockReturnValue("visible");
    act(() => document.dispatchEvent(new Event("visibilitychange"))); await flush();
    expect(loader).toHaveBeenCalledTimes(1);
    act(() => result.current.refresh()); await flush();
    expect(loader).toHaveBeenCalledTimes(2);
    expect(result.current.status).toBe("READY");
  });

  it("does not start a read while initially hidden", async () => {
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    const { result } = renderHook(() => useSentryResearchFeed({ enabled: true }));
    act(() => result.current.refresh()); await flush();
    expect(result.current.status).toBe("DISABLED");
    expect(loader).not.toHaveBeenCalled();
  });

  it("manual refresh cancels an in-flight request before replacement", async () => {
    loader.mockImplementationOnce(() => new Promise(() => {}));
    const { result } = renderHook(() => useSentryResearchFeed({ enabled: true }));
    const signal = loader.mock.calls[0][0]?.signal;
    act(() => result.current.refresh()); await flush();
    expect(signal?.aborted).toBe(true);
    expect(loader).toHaveBeenCalledTimes(2);
    expect(result.current.status).toBe("READY");
  });
});
