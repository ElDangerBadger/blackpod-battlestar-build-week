import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useLiveNavigatorPrice } from "./useLiveNavigatorPrice";

class Stream {
  static instances: Stream[] = [];
  onmessage: ((message: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();
  constructor(readonly url: string) { Stream.instances.push(this); }
  emit(changes: Record<string, unknown> = {}) {
    this.onmessage?.({ data: JSON.stringify({ schema_version: "navigator.live_price.v1", symbol: "AAPL",
      provider: "alpaca", feed: "iex", status: "LIVE", price: 330.12, trade_at: "2026-09-16T20:00:00Z",
      received_at: "2026-09-16T20:00:00Z", checked_at: new Date().toISOString(), message: "Read-only market data.", ...changes }) } as MessageEvent);
  }
}
const options = { publicationId: "a".repeat(64), symbol: "AAPL", enabled: true };
const last = () => Stream.instances.at(-1)!;

describe("live price stream lifetime", () => {
  beforeEach(() => {
    Stream.instances = [];
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-16T20:00:00Z"));
    vi.stubGlobal("EventSource", Stream);
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it("opens one same-origin stream, retains actual quotes, and closes on unmount", () => {
    const { result, unmount } = renderHook(() => useLiveNavigatorPrice(options));
    expect(last().url).toBe(`/live/navigator/price/${options.publicationId}/AAPL`);
    expect(Stream.instances).toHaveLength(1);
    act(() => last().emit());
    expect(result.current.quote?.price).toBe(330.12);
    expect(result.current.status).toBe("LIVE");
    const source = last();
    const late = source.onmessage;
    unmount();
    expect(source.close).toHaveBeenCalledTimes(1);
    act(() => late?.({ data: "{}" } as MessageEvent));
    act(() => vi.advanceTimersByTime(20_000));
    expect(Stream.instances).toHaveLength(1);
  });

  it.each([{ enabled: false }, { publicationId: null }, { publicationId: "invalid" }, { symbol: "../SPY" }])("never opens an ineligible subscription %j", (changes) => {
    renderHook(() => useLiveNavigatorPrice({ ...options, ...changes }));
    expect(Stream.instances).toHaveLength(0);
  });

  it("atomically discards another symbol or publication's quote and closes old connections", () => {
    const { result, rerender } = renderHook((props) => useLiveNavigatorPrice(props), { initialProps: options });
    act(() => last().emit());
    const source = last();
    const late = source.onmessage;
    rerender({ ...options, symbol: "SPY" });
    expect(source.close).toHaveBeenCalledTimes(1);
    expect(result.current.quote).toBeNull();
    act(() => late?.({ data: "{}" } as MessageEvent));
    act(() => last().emit({ symbol: "SPY", price: 660 }));
    expect(result.current.quote?.symbol).toBe("SPY");
    rerender({ ...options, symbol: "SPY", publicationId: "b".repeat(64) });
    expect(result.current.quote).toBeNull();
    expect(Stream.instances).toHaveLength(3);
  });

  it("closes on errors and reconnects at a bounded rate without overlapping or clearing the last quote", () => {
    const { result } = renderHook(() => useLiveNavigatorPrice(options));
    act(() => last().emit());
    const source = last();
    act(() => source.onerror?.());
    expect(source.close).toHaveBeenCalledTimes(1);
    expect(result.current.status).toBe("UNAVAILABLE");
    expect(result.current.quote?.price).toBe(330.12);
    act(() => vi.advanceTimersByTime(4_999));
    expect(Stream.instances).toHaveLength(1);
    act(() => vi.advanceTimersByTime(1));
    expect(Stream.instances).toHaveLength(2);
    expect(result.current.status).toBe("CONNECTING");
  });

  it("rejects wrong-symbol, malformed and out-of-order updates without losing the last good price", () => {
    const { result } = renderHook(() => useLiveNavigatorPrice(options));
    act(() => last().emit());
    act(() => last().emit({ symbol: "SPY", price: 666 }));
    expect(result.current.status).toBe("UNAVAILABLE");
    expect(result.current.quote?.price).toBe(330.12);
    act(() => vi.advanceTimersByTime(5_000));
    act(() => last().emit({ trade_at: "2026-09-16T19:59:59Z", price: 320 }));
    expect(result.current.quote?.price).toBe(330.12);
    expect(result.current.status).toBe("UNAVAILABLE");
  });

  it("uses trade time, not recent heartbeat time, for the one-minute stale boundary", () => {
    const { result } = renderHook(() => useLiveNavigatorPrice(options));
    act(() => last().emit());
    for (let count = 0; count < 5; count++) {
      act(() => vi.advanceTimersByTime(10_000));
      act(() => last().emit());
    }
    act(() => vi.advanceTimersByTime(9_000));
    act(() => last().emit());
    expect(result.current.status).toBe("LIVE");
    act(() => vi.advanceTimersByTime(1_000));
    expect(result.current.status).toBe("STALE");
    act(() => last().emit({ trade_at: new Date().toISOString(), received_at: new Date().toISOString(), price: 330.2 }));
    expect(result.current.status).toBe("LIVE");
  });

  it("stops hidden or paused streams and resumes only when both visible and enabled", () => {
    const { result, rerender } = renderHook((props) => useLiveNavigatorPrice(props), { initialProps: options });
    act(() => last().emit());
    const source = last();
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(source.close).toHaveBeenCalledTimes(1);
    expect(result.current.status).toBe("PAUSED");
    act(() => vi.advanceTimersByTime(10_000));
    expect(Stream.instances).toHaveLength(1);
    rerender({ ...options, enabled: false });
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(Stream.instances).toHaveLength(1);
    rerender(options);
    expect(Stream.instances).toHaveLength(2);
    expect(result.current.quote?.price).toBe(330.12);
    expect(result.current.status).toBe("CONNECTING");
    act(() => last().emit({ trade_at: "2026-09-16T19:59:59Z", price: 310 }));
    expect(result.current.status).toBe("UNAVAILABLE");
    expect(result.current.quote?.price).toBe(330.12);
  });

  it("does not resurrect an older quote after a no-price status message", () => {
    const { result } = renderHook(() => useLiveNavigatorPrice(options));
    act(() => last().emit());
    act(() => last().emit({ status: "WAITING", price: null, trade_at: null, received_at: null }));
    expect(result.current.status).toBe("WAITING");
    act(() => last().emit({ trade_at: "2026-09-16T19:59:59Z", price: 300 }));
    expect(result.current.quote?.price).toBe(330.12);
    expect(result.current.status).toBe("UNAVAILABLE");
  });

  it("times out a silent connection and exponentially backs off repeated failures up to 30 seconds", () => {
    const { result } = renderHook(() => useLiveNavigatorPrice(options));
    const first = last();
    act(() => vi.advanceTimersByTime(20_000));
    expect(first.close).toHaveBeenCalledTimes(1);
    expect(result.current.status).toBe("UNAVAILABLE");
    act(() => vi.advanceTimersByTime(5_000));
    expect(Stream.instances).toHaveLength(2);
    act(() => last().onerror?.());
    act(() => vi.advanceTimersByTime(9_999));
    expect(Stream.instances).toHaveLength(2);
    act(() => vi.advanceTimersByTime(1));
    expect(Stream.instances).toHaveLength(3);
    act(() => last().onerror?.());
    act(() => vi.advanceTimersByTime(20_000));
    expect(Stream.instances).toHaveLength(4);
    act(() => last().onerror?.());
    act(() => vi.advanceTimersByTime(30_000));
    expect(Stream.instances).toHaveLength(5);
  });
});
