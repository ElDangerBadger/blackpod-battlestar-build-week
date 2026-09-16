import { describe, expect, it } from "vitest";
import { liveNavigatorPriceUrl, livePriceStatus, navigatorPublicationId, validateLiveNavigatorPrice, type LiveNavigatorPriceEvent } from "./liveNavigatorPrice";

const now = Date.parse("2026-09-16T20:00:00Z");
const event = (changes: Partial<LiveNavigatorPriceEvent> = {}): LiveNavigatorPriceEvent => ({
  schema_version: "navigator.live_price.v1", symbol: "AAPL", provider: "alpaca", feed: "iex", status: "LIVE",
  price: 330.12, trade_at: "2026-09-16T19:59:59.123456789Z", received_at: "2026-09-16T20:00:00Z",
  checked_at: "2026-09-16T20:00:00Z", message: "Read-only market data.", ...changes,
});

describe("read-only live Navigator message boundary", () => {
  it("only derives same-origin paths from immutable publication IDs and safe symbols", () => {
    const id = "a".repeat(64);
    expect(navigatorPublicationId(`/live/revisions/${id}/`)).toBe(id);
    expect(liveNavigatorPriceUrl(id, "BRK.B")).toBe(`/live/navigator/price/${id}/BRK.B`);
    for (const path of [`https://other/live/revisions/${id}/`, `//other/live/revisions/${id}/`, `/live/revisions/${id}/extra`, "./demo/approved/"]) expect(navigatorPublicationId(path)).toBeNull();
    for (const symbol of ["../AAPL", "AAPL?key=secret", "aapl", "", "AAPL/SPY"]) expect(liveNavigatorPriceUrl(id, symbol)).toBeNull();
    expect(liveNavigatorPriceUrl("not-a-publication", "AAPL")).toBeNull();
  });

  it("accepts nanosecond timestamps and preserves a valid provider message without deriving a price", () => {
    const input = Object.freeze(event());
    expect(validateLiveNavigatorPrice(input, "AAPL", now)).toBe(input);
    expect(livePriceStatus(input, now)).toBe("LIVE");
  });

  it.each([
    { symbol: "SPY" }, { provider: "yfinance" }, { feed: "delayed_sip" }, { status: "APPROVED" },
    { schema_version: "other" }, { unexpected: true }, { price: 0 }, { price: -1 }, { price: Infinity },
    { price: NaN }, { price: "330" }, { price: true }, { trade_at: null }, { received_at: null },
    { checked_at: "2026-09-16T20:00:06Z" }, { trade_at: "2026-09-16T20:00:06Z" },
    { received_at: "2026-09-16T20:00:06Z" }, { trade_at: "2026-09-16T19:59:59+00:00" },
    { trade_at: "2026-02-30T19:59:59Z" }, { received_at: "2026-09-16T19:00:00Z" },
    { message: "a".repeat(201) }, { message: "unsafe\nmessage" }, { price: null, trade_at: null, received_at: null },
  ])("rejects malformed, unsafe or mismatched message %j", (changes) => {
    expect(() => validateLiveNavigatorPrice({ ...event(), ...changes }, "AAPL", now)).toThrow("unavailable or invalid");
  });

  it("permits explicit waiting/unavailable with no invented price", () => {
    expect(validateLiveNavigatorPrice(event({ status: "WAITING", price: null, trade_at: null, received_at: null }), "AAPL", now).price).toBeNull();
  });

  it("bounds clock skew to five seconds", () => {
    expect(validateLiveNavigatorPrice(event({ trade_at: "2026-09-16T20:00:04Z" }), "AAPL", now).price).toBe(330.12);
  });

  it("rejects reordered trade/receive/check times and a silent feed change", () => {
    const prior = event();
    for (const changes of [
      { trade_at: "2026-09-16T19:59:59.123456788Z" }, { price: 333 },
      { received_at: "2026-09-16T19:59:59Z" }, { checked_at: "2026-09-16T19:59:59Z" }, { feed: "sip" as const },
    ]) expect(() => validateLiveNavigatorPrice(event(changes), "AAPL", now, prior)).toThrow();
    expect(validateLiveNavigatorPrice(event({ trade_at: "2026-09-16T19:59:59.123456790Z", price: 331 }), "AAPL", now, prior).price).toBe(331);
  });

  it("ages a trade rather than its heartbeat and does not upgrade disconnected messages", () => {
    const old = event({ trade_at: "2026-09-16T19:59:00Z" });
    expect(livePriceStatus(old, now - 1)).toBe("LIVE");
    expect(livePriceStatus(old, now)).toBe("STALE");
    expect(livePriceStatus(event({ status: "UNAVAILABLE" }), now)).toBe("UNAVAILABLE");
  });
});
