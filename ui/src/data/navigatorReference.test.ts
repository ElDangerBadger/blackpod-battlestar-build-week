import { describe, expect, it } from "vitest";
import { navigatorReferenceFixture, REFERENCE_NOW, REFERENCE_PUBLICATION } from "../test/navigatorReferenceFixture";
import { navigatorReferenceStatus, navigatorReferenceUrl, validateNavigatorReference } from "./navigatorReference";

const selection = { symbol: "AAPL", timeframe: "1d", ma_period: 250 } as const;
const now = Date.parse(REFERENCE_NOW);

describe("current Navigator reference contract", () => {
  it("accepts matching provider captures without recomputing values", () => {
    const feed = navigatorReferenceFixture();
    expect(validateNavigatorReference(feed, selection, now)).toEqual(feed);
  });
  it("constructs only same-origin bounded selection URLs", () => {
    expect(navigatorReferenceUrl(REFERENCE_PUBLICATION, selection)).toBe(`/live/navigator/reference/${REFERENCE_PUBLICATION}/AAPL/1d/250`);
    expect(navigatorReferenceUrl("bad", selection)).toBeNull();
    expect(navigatorReferenceUrl(REFERENCE_PUBLICATION, { ...selection, symbol: "../AAPL" })).toBeNull();
    expect(navigatorReferenceUrl(REFERENCE_PUBLICATION, null)).toBeNull();
  });
  it.each([
    (feed: ReturnType<typeof navigatorReferenceFixture>) => { feed.snapshot!.symbol = "SPY"; },
    (feed: ReturnType<typeof navigatorReferenceFixture>) => { feed.snapshot!.market.symbol = "SPY"; },
    (feed: ReturnType<typeof navigatorReferenceFixture>) => { feed.snapshot!.ma_period = 20; },
    (feed: ReturnType<typeof navigatorReferenceFixture>) => { feed.snapshot!.market.summary.last_price = 999; },
    (feed: ReturnType<typeof navigatorReferenceFixture>) => { feed.snapshot!.market.points[0].h = 1; },
    (feed: ReturnType<typeof navigatorReferenceFixture>) => { feed.snapshot!.snapshot_id = "not-a-hash"; },
    (feed: ReturnType<typeof navigatorReferenceFixture>) => { feed.snapshot!.market.data!.provider = "synthetic"; },
    (feed: ReturnType<typeof navigatorReferenceFixture>) => { feed.snapshot!.latest_bar_at += 1; },
    (feed: ReturnType<typeof navigatorReferenceFixture>) => { feed.snapshot!.expected_bar_at += 86400; },
    (feed: ReturnType<typeof navigatorReferenceFixture>) => { feed.snapshot!.captured_at = "2026-09-19T00:00:00Z"; },
    (feed: ReturnType<typeof navigatorReferenceFixture>) => { feed.checked_at = "2026-09-19T00:00:00Z"; },
    (feed: ReturnType<typeof navigatorReferenceFixture>) => { feed.snapshot!.provider_fetched_at = "2026-09-19T00:00:00Z"; },
    (feed: ReturnType<typeof navigatorReferenceFixture>) => { feed.snapshot!.provider_fetched_at = "2026-09-16T00:00:00Z"; },
    (feed: ReturnType<typeof navigatorReferenceFixture>) => { feed.snapshot!.calendar_id = "unverified-calendar"; },
    (feed: ReturnType<typeof navigatorReferenceFixture>) => { feed.snapshot!.valid_until = feed.snapshot!.captured_at; },
    (feed: ReturnType<typeof navigatorReferenceFixture>) => { feed.snapshot!.valid_until = "2026-09-29T00:00:00Z"; },
    (feed: ReturnType<typeof navigatorReferenceFixture>) => { feed.status = "STALE"; feed.snapshot!.expected_bar_at += 86400; },
    (feed: ReturnType<typeof navigatorReferenceFixture>) => { feed.status = "STALE"; feed.snapshot!.market.data!.stale = true; },
    (feed: ReturnType<typeof navigatorReferenceFixture>) => { feed.snapshot!.market.points.at(-1)!.ma = null; feed.snapshot!.market.summary.last_ma = null; },
  ])("rejects malformed, mismatched or future reference evidence", (mutate) => {
    const feed = navigatorReferenceFixture(); mutate(feed);
    expect(() => validateNavigatorReference(feed, selection, now)).toThrow();
  });
  it("does not allow heartbeat freshness to revive expired data", () => {
    const feed = navigatorReferenceFixture();
    feed.snapshot!.valid_until = "2026-09-18T14:59:59Z";
    const parsed = validateNavigatorReference(feed, selection, now);
    expect(navigatorReferenceStatus(parsed.status, parsed.snapshot, now)).toBe("STALE");
  });
  it("unavailable endpoints cannot quietly include an unverified replacement", () => {
    const feed = navigatorReferenceFixture(); feed.status = "UNAVAILABLE";
    expect(() => validateNavigatorReference(feed, selection, now)).toThrow();
    feed.snapshot = null;
    expect(validateNavigatorReference(feed, selection, now)).toEqual(feed);
    feed.status = "READY";
    expect(() => validateNavigatorReference(feed, selection, now)).toThrow();
  });
});
