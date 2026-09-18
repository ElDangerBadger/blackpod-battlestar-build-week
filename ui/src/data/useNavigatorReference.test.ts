import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { navigatorReferenceFixture, REFERENCE_NOW, REFERENCE_PUBLICATION } from "../test/navigatorReferenceFixture";
import { useNavigatorReference } from "./useNavigatorReference";

const options = { publicationId: REFERENCE_PUBLICATION, selection: { symbol: "AAPL" as string, timeframe: "1d", ma_period: 250 } as const, enabled: true };
const response = (value = navigatorReferenceFixture()) => new Response(JSON.stringify(value), { headers: { "content-type": "application/json" } });
describe("selected current-reference polling", () => {
  beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(new Date(REFERENCE_NOW)); });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  it("polls only the selected pair every minute, stops on unmount, and never mutates source data", async () => {
    const feed = navigatorReferenceFixture(), before = JSON.stringify(feed);
    const fetch = vi.fn(async (_url: string, _init?: RequestInit) => response(feed)); vi.stubGlobal("fetch", fetch);
    const { result, unmount } = renderHook(() => useNavigatorReference(options));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(result.current.status).toBe("READY");
    expect(result.current.snapshot?.market.summary.last_price).toBe(334);
    expect(fetch.mock.calls[0][0]).toBe(`/live/navigator/reference/${REFERENCE_PUBLICATION}/AAPL/1d/250`);
    await act(async () => { await vi.advanceTimersByTimeAsync(59_999); });
    expect(fetch).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(fetch).toHaveBeenCalledTimes(2);
    unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(120_000); });
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(JSON.stringify(feed)).toBe(before);
  });
  it.each([{ enabled: false }, { publicationId: null }, { publicationId: "invalid" }])("never fetches disabled or ineligible sources %j", async (change) => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    renderHook(() => useNavigatorReference({ ...options, ...change }));
    await act(async () => { await vi.advanceTimersByTimeAsync(120_000); });
    expect(fetch).not.toHaveBeenCalled();
  });
  it("keeps the last good snapshot marked stale when later refresh fails", async () => {
    const fetch = vi.fn().mockResolvedValueOnce(response()).mockRejectedValue(new Error("offline")); vi.stubGlobal("fetch", fetch);
    const { result } = renderHook(() => useNavigatorReference(options));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    const snapshot = result.current.snapshot;
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(result.current.status).toBe("STALE");
    expect(result.current.snapshot).toEqual(snapshot);
  });
  it("retains the same snapshot object across identical feed polls", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response()));
    const { result } = renderHook(() => useNavigatorReference(options));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    const snapshot = result.current.snapshot;
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(result.current.status).toBe("READY");
    expect(result.current.snapshot).toBe(snapshot);
  });
  it("rejects capture rollback after saved-source pause and resume", async () => {
    const older = navigatorReferenceFixture();
    older.snapshot!.captured_at = "2026-09-18T14:58:30Z";
    older.snapshot!.provider_fetched_at = "2026-09-18T14:58:29Z";
    older.snapshot!.snapshot_id = "d".repeat(64);
    const fetch = vi.fn().mockResolvedValueOnce(response()).mockResolvedValueOnce(response(older));
    vi.stubGlobal("fetch", fetch);
    const { result, rerender } = renderHook((props: Parameters<typeof useNavigatorReference>[0]) => useNavigatorReference(props), { initialProps: options });
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    const snapshot = result.current.snapshot;
    rerender({ ...options, enabled: false });
    await act(async () => { await vi.advanceTimersByTimeAsync(120_000); });
    expect(fetch).toHaveBeenCalledTimes(1);
    rerender(options);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(result.current.status).toBe("STALE");
    expect(result.current.snapshot).toBe(snapshot);
  });
  it("expires from valid_until even with no new heartbeat", async () => {
    const feed = navigatorReferenceFixture(); feed.snapshot!.valid_until = "2026-09-18T15:00:01Z";
    vi.stubGlobal("fetch", vi.fn(async () => response(feed)));
    const { result } = renderHook(() => useNavigatorReference(options));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(result.current.status).toBe("READY");
    await act(async () => { await vi.advanceTimersByTimeAsync(1_000); });
    expect(result.current.status).toBe("STALE");
  });
  it("does not show another symbol's retained data after selection changes", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(response()).mockRejectedValue(new Error("offline")));
    const { result, rerender } = renderHook((props: Parameters<typeof useNavigatorReference>[0]) => useNavigatorReference(props), { initialProps: options });
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    rerender({ ...options, selection: { ...options.selection, symbol: "SPY" } });
    expect(result.current.snapshot).toBeNull();
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(result.current.status).toBe("UNAVAILABLE");
    expect(result.current.snapshot).toBeNull();
  });
  it("aborts a hung request and never overlaps polls", async () => {
    const fetch = vi.fn((_url: string, init: RequestInit) => new Promise((_resolve, reject) => init.signal?.addEventListener("abort", () => reject(new Error("aborted")))));
    vi.stubGlobal("fetch", fetch);
    const { result } = renderHook(() => useNavigatorReference(options));
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(result.current.status).toBe("UNAVAILABLE");
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
