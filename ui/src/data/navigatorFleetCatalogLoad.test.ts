import { describe, expect, it, vi } from "vitest";
import type { NavigatorMarket } from "../contracts/cabinContext";
import type { NavigatorFleetCatalogV1 } from "../contracts/navigatorFleetCatalog";
import { PRESENTATION_MANIFEST_SCHEMA, type ArtifactReference, type JsonObject, type PresentationManifestV1 } from "../contracts/presentation";
import { artifact, createMissionBundleFixture } from "../test/missionFixture";
import { loadMissionBundle, type LoadMissionBundleOptions } from "./loadMission";
import { parsePresentationManifest } from "./validate";
import { createMissionViewModel } from "./viewModel";

const WHEN = "2026-09-16T17:00:00Z";
const PATH = "presentation/navigator_fleet_catalog.json";
async function digest(bytes: string) {
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(bytes)))].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}
function market(symbol: string): NavigatorMarket {
  return {
    symbol, name: `Recorded ${symbol}`, category: "equity", timeframe: "1d", ma_period: 250, currency: "USD",
    data: { stale: false, age_seconds: 0, source: "provider", provider: "yfinance" },
    points: [{ t: 100, o: 190, h: 194, l: 189, c: 193, v: 1000, ma: 188, atr: 3 }],
    summary: { last_price: 193, last_ma: 188, pct_vs_ma: 2.6596, position: "above", trend_slope_pct: 0.5, volatility: "moderate", atr: 3, atr_pct: 1.5544, ma_period: 250, bar_count: 1 },
  };
}

async function publication(options: {
  includeCatalog?: boolean; includeFleet?: boolean; includeOriginal?: boolean;
  allCapturedPairs?: boolean;
  changeCatalog?: (value: NavigatorFleetCatalogV1) => void;
  changeFleet?: (value: JsonObject) => void;
  changeMarket?: (value: NavigatorMarket) => void;
} = {}) {
  const source = createMissionBundleFixture();
  const { schema_version: _schema, ...manifestBase } = source.manifest;
  const base = { ...manifestBase };
  Reflect.deleteProperty(base, "demo_scenario");
  const manifest: PresentationManifestV1 = { ...base, schema_version: PRESENTATION_MANIFEST_SCHEMA, run_mode: "LIVE", generated_at: WHEN,
    modeldock_mode: "NOT_RECORDED", modeldock_revision_or_service_identity: null, modeldock_provider: null, modeldock_model: null, modeldock_trace_id: null };
  source.summary.run_mode = source.snapshot.run_mode = source.captainsLog.run_mode = "LIVE";
  source.summary.generated_at = source.snapshot.observed_at = source.captainsLog.generated_at = WHEN;
  source.summary.modeldock = { status: "NOT_RECORDED", provider: null, model: null, trace_id: null };
  const files = new Map<string, string>();
  async function reference(name: string, path: string, schema: string | null, document: unknown, producer = "harbormaster"): Promise<ArtifactReference> {
    const bytes = `${JSON.stringify(document)}\n`;
    files.set(path, bytes);
    return { ...artifact(name, path, schema), producer, observed_at: WHEN, sha256: await digest(bytes), byte_size: new TextEncoder().encode(bytes).byteLength };
  }
  const fleet: JsonObject = { normalized_snapshot_id: "normalized-captured", symbol_count: 2, symbols: [{ symbol: "XLK", price: 123 }, { symbol: "XLF", price: 42 }] };
  options.changeFleet?.(fleet);
  const fleetRef = await reference("oracle_normalized_snapshot", "oracle/normalized.json", null, fleet, "oracle");
  if (options.includeFleet !== false) source.snapshot.artifacts.push(fleetRef);
  const baseMarket = market("AAPL");
  if (options.includeOriginal !== false) {
    const baseRef = await reference("navigator_market", "presentation/navigator_market.json", "navigator.api.ohlc.v1", baseMarket, "navigator");
    const context = { schema_version: "blackpod.cabin_context.v1", mission_id: source.summary.mission_id, request_id: source.summary.request_id, symbol: "AAPL", run_mode: "LIVE", captured_at: WHEN,
      market_artifact: baseRef, portfolio_artifact: null, capture_provenance: {
        market: { status: "CAPTURED", transport: "LOCAL_JSON", source_identity: "original-reference", navigator_git_revision: "a".repeat(40) },
        portfolio: { status: "NOT_CONFIGURED", transport: null, source_identity: null },
      } };
    manifest.cabin_context = await reference("cabin_context", "presentation/cabin_context.json", "blackpod.cabin_context.v1", context);
    const oldMarket = { ...baseMarket, timeframe: "1h" as const, ma_period: 20 as const, summary: { ...baseMarket.summary, ma_period: 20 as const } };
    const oldRef = await reference("navigator_market_variant", "presentation/navigator_variants/1h-ma20.json", "navigator.api.ohlc.v1", oldMarket, "navigator");
    manifest.navigator_catalog = await reference("navigator_catalog", "presentation/navigator_catalog.json", "blackpod.navigator_catalog.v1", {
      schema_version: "blackpod.navigator_catalog.v1", mission_id: source.summary.mission_id, request_id: source.summary.request_id, symbol: "AAPL", run_mode: "LIVE", captured_at: WHEN,
      entries: [{ timeframe: "1h", ma_period: 20, captured_at: WHEN, transport: "HTTP", source_identity: "old-canonical-capture", navigator_git_revision: "a".repeat(40), artifact: oldRef }],
    });
  }
  const variant = market("XLK");
  options.changeMarket?.(variant);
  const variantRef = await reference("navigator_fleet_market", "presentation/navigator_fleet/XLK-1d-ma250.json", "navigator.api.ohlc.v1", variant, "navigator");
  const catalog: NavigatorFleetCatalogV1 = {
    schema_version: "blackpod.navigator_fleet_catalog.v1", mission_id: source.summary.mission_id, request_id: source.summary.request_id,
    mission_symbol: source.summary.symbol, run_mode: "LIVE", captured_at: WHEN, fleet_snapshot: fleetRef,
    navigator_source: { git_revision: "b".repeat(40), backend_sha256: "c".repeat(64), worktree_dirty: true },
    entries: [{ symbol: "XLK", timeframe: "1d", ma_period: 250, captured_at: WHEN, transport: "HTTP", source_identity: "canonical-fleet-capture", artifact: variantRef }],
  };
  if (options.allCapturedPairs) {
    for (const timeframe of ["1h", "1d", "1wk"] as const) {
      for (const ma_period of [20, 50, 100, 200, 250] as const) {
        if (timeframe === "1d" && ma_period === 250) continue;
        const value = { ...variant, timeframe, ma_period, summary: { ...variant.summary, ma_period } };
        const ref = await reference("navigator_fleet_market", `presentation/navigator_fleet/XLK-${timeframe}-ma${ma_period}.json`, "navigator.api.ohlc.v1", value, "navigator");
        catalog.entries = [...catalog.entries, { symbol: "XLK", timeframe, ma_period, captured_at: WHEN, transport: "HTTP", source_identity: "canonical-fleet-capture", artifact: ref }];
      }
    }
  }
  options.changeCatalog?.(catalog);
  const catalogRef = await reference("navigator_fleet_catalog", PATH, catalog.schema_version, catalog);
  if (options.includeCatalog !== false) manifest.navigator_fleet_catalog = catalogRef;
  manifest.final_snapshot = await reference("mission_snapshot", "mission_snapshot.json", source.snapshot.schema_version, source.snapshot);
  const immutable = { ...manifest.final_snapshot, name: "mission_snapshot_r0013", path: "snapshots/mission_snapshot-r0013.json" };
  files.set(immutable.path, files.get("mission_snapshot.json")!);
  source.summary.generated_from_snapshot = immutable;
  source.captainsLog.generated_from_snapshot = { ...immutable };
  manifest.mission_summary = await reference("mission_summary", "presentation/mission_summary.json", source.summary.schema_version, source.summary);
  manifest.captains_log = await reference("captains_log", "presentation/captains_log.json", source.captainsLog.schema_version, source.captainsLog);
  files.set("presentation/manifest.json", `${JSON.stringify(manifest)}\n`);
  const fetchImpl = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const bytes = files.get(String(input).replace(/^\.\/fleet-publication\//, ""));
    return bytes === undefined ? new Response("Missing", { status: 404 }) : new Response(bytes);
  });
  const load = async (overrides: Partial<LoadMissionBundleOptions> = {}) => loadMissionBundle("./fleet-publication/", { fetchImpl: fetchImpl as typeof fetch,
    manifestKind: "live", expectedManifestSha256: await digest(files.get("presentation/manifest.json")!), ...overrides });
  return { files, source, manifest, catalog, fleet, variant, fetchImpl, load };
}

describe("hash-bound Navigator fleet publications", () => {
  it("loads captured markets at bounded concurrency while preserving catalog order and exact provenance", async () => {
    const fixture = await publication({ allCapturedPairs: true });
    const transport = fixture.fetchImpl.getMockImplementation()!;
    let active = 0;
    let maximum = 0;
    const completed: string[] = [];
    fixture.fetchImpl.mockImplementation(async (input, init) => {
      const path = String(input);
      if (!path.includes("/navigator_fleet/")) return transport(input, init);
      active++;
      maximum = Math.max(maximum, active);
      const originalFirst = path.endsWith("XLK-1d-ma250.json");
      await new Promise((resolve) => setTimeout(resolve, originalFirst ? 40 : 2));
      const response = await transport(input, init);
      active--;
      completed.push(path);
      return response;
    });
    const loaded = await fixture.load();
    expect(maximum).toBe(4);
    expect(completed[0]).not.toContain("XLK-1d-ma250.json");
    expect(loaded.navigatorFleetVariants?.map((item) => item.reference)).toEqual(fixture.catalog.entries.map((item) => item.artifact));
    expect(loaded.navigatorFleetVariants?.every((item) => item.sourceIdentity === "canonical-fleet-capture"
      && item.navigatorSourceSha256 === "c".repeat(64) && item.navigatorWorktreeDirty)).toBe(true);
  });

  it("cancels all in-flight capture requests and never schedules the remaining catalog", async () => {
    const fixture = await publication({ allCapturedPairs: true });
    const transport = fixture.fetchImpl.getMockImplementation()!;
    const controller = new AbortController();
    const signals: AbortSignal[] = [];
    fixture.fetchImpl.mockImplementation(async (input, init) => {
      if (!String(input).includes("/navigator_fleet/")) return transport(input, init);
      const signal = init!.signal!;
      signals.push(signal);
      return new Promise<Response>((_resolve, reject) => signal.addEventListener("abort", () => reject(new Error("cancelled")), { once: true }));
    });
    const loading = fixture.load({ signal: controller.signal });
    const rejected = expect(loading).rejects.toThrow(/cancelled|could not be fetched/);
    await vi.waitFor(() => expect(signals).toHaveLength(4));
    controller.abort();
    await rejected;
    expect(signals.every((signal) => signal === controller.signal && signal.aborted)).toBe(true);
    expect(signals).toHaveLength(4);
  });

  it("rejects the complete publication when one concurrent capture fails its hash", async () => {
    const fixture = await publication({ allCapturedPairs: true });
    const badPath = fixture.catalog.entries[0].artifact.path;
    fixture.files.set(badPath, `${fixture.files.get(badPath)!} `);
    const transport = fixture.fetchImpl.getMockImplementation()!;
    let captures = 0;
    fixture.fetchImpl.mockImplementation(async (input, init) => {
      const path = String(input);
      if (path.includes("/navigator_fleet/")) {
        captures++;
        if (!path.endsWith(badPath)) await new Promise((resolve) => setTimeout(resolve, 40));
      }
      return transport(input, init);
    });
    await expect(fixture.load()).rejects.toThrow(/byte size|SHA-256/);
    await new Promise((resolve) => setTimeout(resolve, 80));
    expect(captures).toBe(4);
  });

  it("loads exact fleet captures separately from the untouched original and single-symbol variants", async () => {
    const fixture = await publication();
    const loaded = await fixture.load();
    expect(loaded.navigatorMarket).toEqual(market("AAPL"));
    expect(loaded.navigatorVariants).toHaveLength(1);
    expect(loaded.navigatorVariants?.[0].market.symbol).toBe("AAPL");
    expect(loaded.navigatorFleetVariants).toEqual([{
      market: fixture.variant, capturedAt: WHEN, sourceIdentity: "canonical-fleet-capture", navigatorGitRevision: "b".repeat(40),
      navigatorSourceSha256: "c".repeat(64), navigatorWorktreeDirty: true, reference: fixture.catalog.entries[0].artifact,
    }]);
    const view = createMissionViewModel(loaded);
    expect(view.market.navigatorFleetVariants).toBe(loaded.navigatorFleetVariants);
    expect(view.market.navigatorMarket).toBe(loaded.navigatorMarket);
    expect(view.status.symbol).toBe("AAPL");
    expect(view.status.outcome).toBe("APPROVED");
    const paths = fixture.fetchImpl.mock.calls.map(([url]) => String(url));
    expect(paths.indexOf("./fleet-publication/oracle/normalized.json")).toBeLessThan(paths.indexOf(`./fleet-publication/${PATH}`));
  });

  it("does not fetch an unreferenced fleet catalog or use it to seed datasets", async () => {
    const fixture = await publication({ includeCatalog: false });
    const loaded = await fixture.load();
    expect(loaded.navigatorFleetVariants).toEqual([]);
    expect(fixture.fetchImpl.mock.calls.some(([url]) => String(url).includes("navigator_fleet"))).toBe(false);
  });

  it("can load fleet captures without an unrelated original market context", async () => {
    const fixture = await publication({ includeOriginal: false });
    const loaded = await fixture.load();
    expect(loaded.navigatorMarket).toBeNull();
    expect(loaded.navigatorVariants).toEqual([]);
    expect(loaded.navigatorFleetVariants?.[0].market.symbol).toBe("XLK");
  });

  it.each([PATH, "presentation/navigator_fleet/XLK-1d-ma250.json", "oracle/normalized.json"])("rejects changed exact bytes at %s", async (path) => {
    const fixture = await publication();
    fixture.files.set(path, `${fixture.files.get(path)} `);
    await expect(fixture.load()).rejects.toThrow(/byte size|SHA-256|verified canonical normalized/);
  });

  it.each([PATH, "presentation/navigator_fleet/XLK-1d-ma250.json", "oracle/normalized.json"])("rejects missing referenced bytes at %s", async (path) => {
    const fixture = await publication();
    fixture.files.delete(path);
    await expect(fixture.load()).rejects.toThrow(/HTTP 404|verified canonical normalized/);
  });

  it.each(["symbol", "timeframe", "MA", "synthetic"])("rejects rehashed body mismatch: %s", async (kind) => {
    const fixture = await publication({ changeMarket: (value) => {
      if (kind === "symbol") value.symbol = "XLF";
      if (kind === "timeframe") value.timeframe = "1wk";
      if (kind === "MA") value.ma_period = value.summary.ma_period = 50;
      if (kind === "synthetic") value.data!.provider = "synthetic";
    } });
    await expect(fixture.load()).rejects.toThrow(/symbol|timeframe\/MA|synthetic/);
  });

  it.each(["mission", "request", "anchor", "membership", "snapshot", "capture-time"])("rejects rehashed catalog mismatch: %s", async (kind) => {
    const fixture = await publication({ changeCatalog: (value) => {
      if (kind === "mission") value.mission_id = "another-mission";
      if (kind === "request") value.request_id = "another-request";
      if (kind === "anchor") value.mission_symbol = "MSFT";
      if (kind === "membership") { value.entries[0].symbol = "MSFT"; value.entries[0].artifact.path = "presentation/navigator_fleet/MSFT-1d-ma250.json"; }
      if (kind === "snapshot") value.fleet_snapshot = { ...value.fleet_snapshot, sha256: "f".repeat(64) };
      if (kind === "capture-time") value.captured_at = "2026-09-16T16:00:00Z";
    } });
    await expect(fixture.load()).rejects.toThrow(/correlation|observed fleet member|snapshot reference|capture time/);
  });

  it("requires canonical indexed fleet evidence even outside strictEvidence mode", async () => {
    const fixture = await publication({ includeFleet: false });
    await expect(fixture.load()).rejects.toThrow(/verified canonical normalized/);
    expect(fixture.fetchImpl.mock.calls.some(([url]) => String(url).includes("navigator_fleet"))).toBe(false);
  });

  it.each(["missing", "duplicate", "count"])("fails closed on rehashed malformed normalized fleet: %s", async (kind) => {
    const fixture = await publication({ changeFleet: (value) => {
      if (kind === "missing") delete value.symbols;
      if (kind === "duplicate") value.symbols = [{ symbol: "XLK" }, { symbol: "XLK" }];
      if (kind === "count") value.symbol_count = 3;
    } });
    await expect(fixture.load()).rejects.toThrow(/normalized snapshot|supported and unique/);
  });

  it.each([
    { name: "navigator_catalog" }, { path: "presentation/other.json" }, { schema_version: "other" },
    { producer: "navigator" }, { observed_at: null }, { byte_size: null }, { byte_size: Number.MAX_SAFE_INTEGER + 1 },
  ])("rejects an invalid LIVE manifest reference %j", async (change) => {
    const fixture = await publication();
    expect(() => parsePresentationManifest({ ...fixture.manifest, navigator_fleet_catalog: { ...fixture.manifest.navigator_fleet_catalog, ...change } })).toThrow();
  });

  it("requires LIVE mode and leaves old replay manifests unchanged", async () => {
    const fixture = await publication();
    expect(() => parsePresentationManifest({ ...fixture.manifest, run_mode: "REPLAY" })).toThrow(/LIVE Navigator/);
    const legacy = createMissionBundleFixture();
    expect(createMissionViewModel(legacy).market.navigatorFleetVariants).toEqual([]);
    expect(legacy.manifest).not.toHaveProperty("navigator_fleet_catalog");
  });
});
