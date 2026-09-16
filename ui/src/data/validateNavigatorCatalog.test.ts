import { describe, expect, it } from "vitest";
import { parseNavigatorCatalog } from "./validateNavigatorCatalog";

const WHEN = "2026-09-15T23:30:00Z";
const correlation = { mission_id: "mission-live-001", request_id: "request-live-001", symbol: "AAPL", run_mode: "LIVE" as const };
const defaultMarket = { timeframe: "1d" as const, ma_period: 250 as const };

function catalog() {
  return {
    schema_version: "blackpod.navigator_catalog.v1", ...correlation, captured_at: WHEN,
    entries: [{
      timeframe: "1h", ma_period: 20, captured_at: "2026-09-15T23:29:00Z", transport: "HTTP",
      source_identity: "navigator-local-api", navigator_git_revision: "a".repeat(40),
      artifact: {
        name: "navigator_market_variant", path: "presentation/navigator_variants/1h-ma20.json",
        sha256: "b".repeat(64), byte_size: 300, producer: "navigator",
        schema_version: "navigator.api.ohlc.v1", observed_at: "2026-09-15T23:29:00Z",
      },
    }],
  };
}

describe("publication-bound Navigator catalog", () => {
  it("preserves capture metadata and never changes the original default pair", () => {
    const source = catalog();
    expect(parseNavigatorCatalog(source, correlation, defaultMarket)).toEqual(source);
    expect(defaultMarket).toEqual({ timeframe: "1d", ma_period: 250 });
  });

  it.each([
    { schema_version: "blackpod.navigator_catalog.v2" },
    { mission_id: "mission-other" }, { request_id: "request-other" }, { symbol: "MSFT" },
    { run_mode: "REPLAY" }, { captured_at: "yesterday" }, { inferred: true }, { entries: [] },
    { entries: Array.from({ length: 16 }, () => catalog().entries[0]) },
  ])("rejects invalid catalog metadata %j", (change) => {
    expect(() => parseNavigatorCatalog({ ...catalog(), ...change }, correlation, defaultMarket)).toThrow();
  });

  it.each([
    { timeframe: "5m" }, { ma_period: 13 }, { ma_period: "20" }, { transport: "BROWSER" },
    { source_identity: "/Users/private" }, { navigator_git_revision: "a".repeat(7) },
    { navigator_git_revision: "A".repeat(40) }, { captured_at: "not-a-date" }, { extra: true },
  ])("rejects unsupported entry metadata %j", (change) => {
    const value = catalog();
    Object.assign(value.entries[0], change);
    expect(() => parseNavigatorCatalog(value, correlation, defaultMarket)).toThrow();
  });

  it.each([
    { name: "navigator_market" }, { producer: "browser" }, { path: "../private.json" },
    { path: "presentation/navigator_variants/1d-ma20.json" }, { schema_version: "other" },
    { byte_size: null }, { byte_size: -1 }, { observed_at: WHEN }, { sha256: "b".repeat(63) },
  ])("rejects inconsistent artifact metadata %j", (change) => {
    const value = catalog();
    Object.assign(value.entries[0].artifact, change);
    expect(() => parseNavigatorCatalog(value, correlation, defaultMarket)).toThrow();
  });

  it("rejects duplicate pairs, including replacing the original default", () => {
    const value = catalog();
    value.entries.push(structuredClone(value.entries[0]));
    expect(() => parseNavigatorCatalog(value, correlation, defaultMarket)).toThrow(/duplicates/);
    expect(() => parseNavigatorCatalog(catalog(), correlation, { timeframe: "1h", ma_period: 20 })).toThrow(/duplicates/);
  });

  it("does not attach LIVE variants to replay evidence", () => {
    expect(() => parseNavigatorCatalog(catalog(), { ...correlation, run_mode: "REPLAY" }, defaultMarket)).toThrow(/LIVE/);
  });

  it("supports every allowed timeframe and MA pair without deriving values", () => {
    const value = catalog();
    value.entries = ["1h", "1d", "1wk"].flatMap((timeframe) => [20, 50, 100, 200, 250]
      .filter((ma) => timeframe !== "1d" || ma !== 250)
      .map((ma_period) => ({
        ...value.entries[0], timeframe, ma_period,
        artifact: { ...value.entries[0].artifact, path: `presentation/navigator_variants/${timeframe}-ma${ma_period}.json` },
      })));
    expect(parseNavigatorCatalog(value, correlation, defaultMarket).entries).toHaveLength(14);
  });
});
