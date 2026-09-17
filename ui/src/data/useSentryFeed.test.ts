import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SentryFeed } from "../contracts/sentry";
import { loadSentryFeed } from "./sentryFeed";
import { SENTRY_POLL_MS, SENTRY_REQUEST_TIMEOUT_MS, useSentryFeed } from "./useSentryFeed";

vi.mock("./sentryFeed", async (importOriginal) => ({ ...await importOriginal<typeof import("./sentryFeed")>(), loadSentryFeed: vi.fn() }));
const feed = (changes: Partial<SentryFeed> = {}): SentryFeed => ({ schema_version: "blackpod.sentry_feed.v1", status: "READY",
  checked_at: "2026-09-16T20:00:00Z", message: "Verified historical research.", observations: [],
  source: { label: "Historical research", kind: "RESEARCH", file_name: "2026-07-15.jsonl", sha256: "a".repeat(64),
    byte_size: 0, latest_observed_at: null, raw_count: 0, duplicate_count: 0 }, ...changes });
const flush = async () => { await act(async () => { await Promise.resolve(); }); };

describe("Sentry archive following lifecycle", () => {
  beforeEach(() => {
    vi.useFakeTimers(); vi.setSystemTime(new Date("2026-09-16T20:00:00Z"));
    vi.mocked(loadSentryFeed).mockReset().mockResolvedValue(feed());
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

  it("polls only an enabled ledger and retains research provenance", async () => {
    const { result, unmount } = renderHook(() => useSentryFeed({ enabled: true }));
    expect(result.current.status).toBe("LOADING");
    await flush();
    expect(result.current.status).toBe("READY");
    expect(result.current.feed?.source?.kind).toBe("RESEARCH");
    await act(() => vi.advanceTimersByTimeAsync(SENTRY_POLL_MS - 1));
    expect(loadSentryFeed).toHaveBeenCalledTimes(1);
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(loadSentryFeed).toHaveBeenCalledTimes(2);
    unmount();
    await act(() => vi.advanceTimersByTimeAsync(SENTRY_POLL_MS));
    expect(loadSentryFeed).toHaveBeenCalledTimes(2);
  });

  it("does not fetch for a closed ledger or replay mode, including manual refresh", async () => {
    const { result } = renderHook(() => useSentryFeed({ enabled: false }));
    act(() => result.current.refresh());
    await act(() => vi.advanceTimersByTimeAsync(SENTRY_POLL_MS * 3));
    expect(result.current.status).toBe("DISABLED");
    expect(result.current.feed).toBeNull();
    expect(loadSentryFeed).not.toHaveBeenCalled();
  });

  it("shows unconfigured without fabricated or fallback observations", async () => {
    vi.mocked(loadSentryFeed).mockResolvedValue(feed({ status: "NOT_CONFIGURED", source: null, message: "No archive configured." }));
    const { result } = renderHook(() => useSentryFeed({ enabled: true }));
    await flush();
    expect(result.current.status).toBe("NOT_CONFIGURED");
    expect(result.current.feed).toBeNull();
    expect(result.current.message).toBe("No archive configured.");
  });

  it("retains the verified archive on errors and recovers without exposing errors", async () => {
    const { result } = renderHook(() => useSentryFeed({ enabled: true }));
    await flush(); const prior = result.current.feed;
    vi.mocked(loadSentryFeed).mockRejectedValueOnce(new Error("private server detail"));
    await act(() => vi.advanceTimersByTimeAsync(SENTRY_POLL_MS));
    expect(result.current.status).toBe("UNAVAILABLE");
    expect(result.current.feed).toBe(prior);
    expect(result.current.message).toContain("last verified archive");
    expect(result.current.message).not.toContain("private");
    await act(() => vi.advanceTimersByTimeAsync(SENTRY_POLL_MS));
    expect(result.current.status).toBe("READY");
  });

  it.each(["NOT_CONFIGURED", "UNAVAILABLE"] as const)("retains old evidence with explicit %s receipt", async (status) => {
    const { result } = renderHook(() => useSentryFeed({ enabled: true }));
    await flush(); const prior = result.current.feed;
    vi.mocked(loadSentryFeed).mockResolvedValue(feed({ status, source: null, message: "Archive not available." }));
    act(() => result.current.refresh()); await flush();
    expect(result.current.status).toBe(status);
    expect(result.current.feed).toBe(prior);
    expect(result.current.message).toContain("has not been refreshed");
  });

  it("rejects an out-of-order receipt without rolling back the last verified archive", async () => {
    const { result } = renderHook(() => useSentryFeed({ enabled: true }));
    await flush(); const prior = result.current.feed;
    vi.mocked(loadSentryFeed).mockResolvedValue(feed({ checked_at: "2026-09-16T19:59:59Z" }));
    act(() => result.current.refresh()); await flush();
    expect(result.current.status).toBe("UNAVAILABLE");
    expect(result.current.feed).toBe(prior);
  });

  it("bounds a hung fetch, prevents concurrent polls and ignores its late response", async () => {
    let resolveFirst!: (value: SentryFeed) => void;
    vi.mocked(loadSentryFeed).mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }));
    const { result } = renderHook(() => useSentryFeed({ enabled: true }));
    await act(() => vi.advanceTimersByTimeAsync(SENTRY_REQUEST_TIMEOUT_MS - 1));
    expect(loadSentryFeed).toHaveBeenCalledTimes(1);
    expect(result.current.status).toBe("LOADING");
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(result.current.status).toBe("UNAVAILABLE");
    expect(vi.mocked(loadSentryFeed).mock.calls[0][0]?.signal?.aborted).toBe(true);
    await act(() => vi.advanceTimersByTimeAsync(SENTRY_POLL_MS));
    expect(result.current.status).toBe("READY");
    resolveFirst(feed({ checked_at: "2026-09-16T20:30:00Z" })); await flush();
    expect(result.current.feed?.checked_at).toBe("2026-09-16T20:00:00Z");
  });

  it("aborts on close and prevents a late result from crossing a reopen", async () => {
    let resolveFirst!: (value: SentryFeed) => void;
    vi.mocked(loadSentryFeed).mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }));
    const { result, rerender } = renderHook((props) => useSentryFeed(props), { initialProps: { enabled: true } });
    const firstSignal = vi.mocked(loadSentryFeed).mock.calls[0][0]?.signal;
    rerender({ enabled: false });
    expect(firstSignal?.aborted).toBe(true);
    rerender({ enabled: true }); await flush();
    expect(result.current.status).toBe("READY");
    resolveFirst(feed({ checked_at: "2026-09-16T20:30:00Z" })); await flush();
    expect(result.current.feed?.checked_at).toBe("2026-09-16T20:00:00Z");
  });

  it("stops polling when hidden, aborts pending work, and refreshes once visible", async () => {
    const visibility = vi.spyOn(document, "visibilityState", "get");
    const { result } = renderHook(() => useSentryFeed({ enabled: true }));
    await flush(); const prior = result.current.feed;
    visibility.mockReturnValue("hidden");
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(result.current.status).toBe("DISABLED");
    expect(result.current.feed).toBe(prior);
    expect(vi.mocked(loadSentryFeed).mock.calls[0][0]?.signal?.aborted).toBe(true);
    await act(() => vi.advanceTimersByTimeAsync(SENTRY_POLL_MS * 3));
    expect(loadSentryFeed).toHaveBeenCalledTimes(1);
    visibility.mockReturnValue("visible");
    act(() => document.dispatchEvent(new Event("visibilitychange"))); await flush();
    expect(result.current.status).toBe("READY");
    expect(loadSentryFeed).toHaveBeenCalledTimes(2);
  });

  it("does not start a request while initially hidden", () => {
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    const { result } = renderHook(() => useSentryFeed({ enabled: true }));
    expect(result.current.status).toBe("DISABLED");
    expect(loadSentryFeed).not.toHaveBeenCalled();
  });

  it("manual refresh aborts an in-flight request before starting another", async () => {
    vi.mocked(loadSentryFeed).mockImplementationOnce(() => new Promise(() => {}));
    const { result } = renderHook(() => useSentryFeed({ enabled: true }));
    const signal = vi.mocked(loadSentryFeed).mock.calls[0][0]?.signal;
    act(() => result.current.refresh()); await flush();
    expect(signal?.aborted).toBe(true);
    expect(loadSentryFeed).toHaveBeenCalledTimes(2);
    expect(result.current.status).toBe("READY");
  });
});
