import { describe, expect, it } from "vitest";
import type { NavigatorFleetCatalogV1 } from "../contracts/navigatorFleetCatalog";
import { artifact } from "../test/missionFixture";
import { navigatorFleetObservedSymbols, parseNavigatorFleetCatalog } from "./validateNavigatorFleetCatalog";

const WHEN = "2026-09-16T17:00:00Z";
const correlation = { mission_id: "mission-live-001", request_id: "request-live-001", symbol: "AAPL", run_mode: "LIVE" as const };
const fleetReference = { ...artifact("oracle_normalized_snapshot", "oracle/normalized.json"), producer: "oracle", byte_size: 600 };
const fleet = { normalized_snapshot_id: "normalized-001", symbol_count: 2, symbols: [{ symbol: "XLK", price: 123.4 }, { symbol: "BRK.B" }] };

function catalog(): NavigatorFleetCatalogV1 {
  return {
    schema_version: "blackpod.navigator_fleet_catalog.v1", mission_id: correlation.mission_id, request_id: correlation.request_id,
    mission_symbol: correlation.symbol, run_mode: "LIVE", captured_at: WHEN, fleet_snapshot: { ...fleetReference },
    navigator_source: { git_revision: "b".repeat(40), backend_sha256: "c".repeat(64), worktree_dirty: true },
    entries: [{ symbol: "XLK", timeframe: "1d", ma_period: 250, captured_at: WHEN, transport: "HTTP", source_identity: "canonical-navigator",
      artifact: { ...artifact("navigator_fleet_market", "presentation/navigator_fleet/XLK-1d-ma250.json", "navigator.api.ohlc.v1"), producer: "navigator", observed_at: WHEN, byte_size: 800 } }],
  };
}

describe("Navigator fleet catalog validation", () => {
  it("preserves a source-attested catalog and its canonical fleet reference exactly", () => {
    const value = catalog();
    const before = structuredClone(value);
    expect(parseNavigatorFleetCatalog(value, correlation, fleetReference, fleet)).toEqual(value);
    expect(value).toEqual(before);
    expect([...navigatorFleetObservedSymbols(fleet)]).toEqual(["XLK", "BRK.B"]);
  });

  it.each([
    "2026-02-31T17:00:00Z", "2026-02-29T17:00:00Z", "1900-02-29T17:00:00Z",
    "2100-02-29T17:00:00Z", "2026-04-31T17:00:00+05:30", "2024-02-30T17:00:00-07:00",
    "2026-01-00T17:00:00Z", "2026-01-32T17:00:00Z", "2026-00-01T17:00:00Z",
    "2026-13-01T17:00:00Z", "2026-01-01T24:00:00Z", "2026-01-01T25:00:00Z",
    "2026-01-01T12:60:00Z", "2026-01-01T12:00:60Z", "2026-01-01T12:00:00+24:00",
    "2026-01-01T12:00:00-12:60", "0000-01-01T00:00:00Z",
    "0001-01-01T00:00:00+00:01", "9999-12-31T23:59:59-00:01",
  ])("rejects impossible calendar/clock values in every fleet timestamp: %s", (invalid) => {
    for (const field of ["catalog", "entry", "entry-artifact", "fleet-snapshot"] as const) {
      const value = catalog();
      const expectedReference = { ...fleetReference };
      if (field === "catalog") value.captured_at = invalid;
      if (field === "entry") {
        value.entries[0].captured_at = invalid;
        value.entries[0].artifact.observed_at = invalid;
      }
      if (field === "entry-artifact") value.entries[0].artifact.observed_at = invalid;
      if (field === "fleet-snapshot") {
        value.fleet_snapshot.observed_at = invalid;
        expectedReference.observed_at = invalid;
      }
      expect(() => parseNavigatorFleetCatalog(value, correlation, expectedReference, fleet), field).toThrow(/timestamp/);
    }
  });

  it.each([
    "2024-02-29T23:59:59Z", "2000-02-29T00:00:00Z", "2400-02-29T00:00:00Z",
    "2026-02-28T23:59:59.123456Z", "2026-04-30T00:00:00.1+05:30",
    "2026-09-16T01:00:00-07:00", "2026-01-01T00:00:00+23:59",
    "2026-12-31T23:59:59-23:59", "2026-09-16T17:00:00+00:00",
    "2026-09-16T17:00:00-00:00", "2026-09-16T17:00:00.123456789Z",
    "0001-01-01T00:00:00Z", "0099-02-28T00:00:00Z", "9999-12-31T23:59:59.999999Z",
  ])("preserves valid RFC 3339 timestamps, offsets and fractional precision: %s", (valid) => {
    const value = catalog();
    value.captured_at = valid;
    value.entries[0].captured_at = valid;
    value.entries[0].artifact.observed_at = valid;
    value.fleet_snapshot.observed_at = valid;
    const before = structuredClone(value);
    expect(parseNavigatorFleetCatalog(value, correlation, { ...fleetReference, observed_at: valid }, fleet)).toEqual(before);
    expect(value).toEqual(before);
  });

  it.each([
    { schema_version: "unknown" }, { mission_id: "another-mission" }, { request_id: "another-request" },
    { mission_symbol: "MSFT" }, { symbol: "XLK" }, { run_mode: "REPLAY" }, { captured_at: "today" },
    { entries: [] }, { entries: Array.from({ length: 1501 }, () => catalog().entries[0]) },
  ])("rejects malformed root metadata %j", (change) => {
    expect(() => parseNavigatorFleetCatalog({ ...catalog(), ...change }, correlation, fleetReference, fleet)).toThrow();
  });

  it.each([
    { git_revision: "b".repeat(7) }, { git_revision: "B".repeat(40) }, { backend_sha256: "x".repeat(64) },
    { worktree_dirty: "true" }, { worktree_dirty: 1 }, { arbitrary: true },
  ])("rejects invalid source attestation %j", (change) => {
    const value = catalog();
    Object.assign(value.navigator_source, change);
    expect(() => parseNavigatorFleetCatalog(value, correlation, fleetReference, fleet)).toThrow();
  });

  it.each([
    { symbol: "MSFT" }, { symbol: "xlk" }, { symbol: "../XLK" }, { symbol: "^GSPC" }, { symbol: "A".repeat(21) },
    { timeframe: "1m" }, { ma_period: 13 }, { ma_period: "250" }, { transport: "BROWSER" },
    { source_identity: "/Users/private" }, { captured_at: "not-a-date" }, { navigator_git_revision: "b".repeat(40) },
  ])("rejects unsupported or nonmember capture metadata %j", (change) => {
    const value = catalog();
    Object.assign(value.entries[0], change);
    expect(() => parseNavigatorFleetCatalog(value, correlation, fleetReference, fleet)).toThrow();
  });

  it.each([
    { name: "navigator_market_variant" }, { producer: "browser" }, { path: "presentation/navigator_fleet/BRK.B-1d-ma250.json" },
    { schema_version: "unknown" }, { observed_at: "2026-09-15T17:00:00Z" }, { byte_size: null },
    { byte_size: Number.MAX_SAFE_INTEGER + 1 }, { sha256: "A".repeat(64) },
  ])("rejects inconsistent fleet market artifact metadata %j", (change) => {
    const value = catalog();
    Object.assign(value.entries[0].artifact, change);
    expect(() => parseNavigatorFleetCatalog(value, correlation, fleetReference, fleet)).toThrow();
  });

  it.each(["name", "path", "sha256", "producer", "byte_size", "schema_version", "observed_at"] as const)("binds exact fleet reference field %s", (key) => {
    const value = catalog();
    const altered = { ...fleetReference, [key]: key === "byte_size" ? 601 : key === "sha256" ? "f".repeat(64) : key === "observed_at" ? WHEN : "changed" };
    expect(() => parseNavigatorFleetCatalog(value, correlation, altered, fleet)).toThrow(/snapshot reference conflicts/);
  });

  it.each([
    null, {}, { symbols: [] }, { symbols: ["XLK"] }, { symbols: [{ symbol: "xlk" }] },
    { symbols: [{ symbol: "XLK" }, { symbol: "XLK" }] },
    { symbols: [{ symbol: "XLK" }], symbol_count: 2 }, { symbols: [{ symbol: "XLK" }], symbol_count: "1" },
    { symbols: Array.from({ length: 101 }, (_, index) => ({ symbol: `S${index}` })) },
  ])("rejects malformed or ambiguous observed membership %j", (value) => {
    expect(() => parseNavigatorFleetCatalog(catalog(), correlation, fleetReference, value)).toThrow();
  });

  it("rejects duplicate triples but permits multiple intervals and captured subsets", () => {
    const value = catalog();
    value.entries = [...value.entries, structuredClone(value.entries[0])];
    expect(() => parseNavigatorFleetCatalog(value, correlation, fleetReference, fleet)).toThrow(/duplicates/);
    value.entries[1].timeframe = "1wk";
    value.entries[1].artifact.path = "presentation/navigator_fleet/XLK-1wk-ma250.json";
    expect(parseNavigatorFleetCatalog(value, correlation, fleetReference, fleet).entries).toHaveLength(2);
  });

  it("permits the mission symbol only when it has no original captured dataset", () => {
    const value = catalog();
    value.entries[0].symbol = "AAPL";
    value.entries[0].artifact.path = "presentation/navigator_fleet/AAPL-1d-ma250.json";
    const observed = { symbols: [{ symbol: "AAPL" }] };
    expect(parseNavigatorFleetCatalog(value, correlation, fleetReference, observed).entries[0].symbol).toBe("AAPL");
    expect(() => parseNavigatorFleetCatalog(value, correlation, fleetReference, observed, { symbol: "AAPL" })).toThrow(/original mission-symbol/);
  });

  it("does not add LIVE fleet data to a replay mission", () => {
    expect(() => parseNavigatorFleetCatalog(catalog(), { ...correlation, run_mode: "REPLAY" }, fleetReference, fleet)).toThrow(/LIVE/);
  });

  it("accepts the 100-member and 1500-entry bounds without creating any missing pairs", () => {
    const value = catalog();
    const symbols = Array.from({ length: 100 }, (_, index) => `S${index}`);
    value.entries = symbols.flatMap((symbol) => (["1h", "1d", "1wk"] as const).flatMap((timeframe) => ([20, 50, 100, 200, 250] as const).map((ma_period) => ({
      ...value.entries[0], symbol, timeframe, ma_period,
      artifact: { ...value.entries[0].artifact, path: `presentation/navigator_fleet/${symbol}-${timeframe}-ma${ma_period}.json` },
    }))));
    expect(parseNavigatorFleetCatalog(value, correlation, fleetReference, { symbol_count: 100, symbols: symbols.map((symbol) => ({ symbol })) }).entries).toHaveLength(1500);
  });
});
