import { describe, expect, it, vi } from "vitest";
import {
  PRESENTATION_MANIFEST_SCHEMA,
  type ModelDockCallContract,
  type PresentationManifestV1,
} from "../contracts/presentation";
import { artifact, createMissionBundleFixture } from "../test/missionFixture";
import { loadMissionBundle, type MissionBundle } from "./loadMission";
import {
  CABIN_FEED_SCHEMA,
  loadLiveMissionBundle,
  loadLiveMissionFeed,
  parseLiveMissionFeed,
  type ReadyLiveMissionFeed,
} from "./liveMission";
import { parsePresentationManifest } from "./validate";
import { createMissionViewModel } from "./viewModel";
import type { NavigatorMarket } from "../contracts/cabinContext";
import type { NavigatorCatalogV1 } from "../contracts/navigatorCatalog";

const WHEN = "2026-09-15T19:00:00Z";

async function digest(payload: string): Promise<string> {
  const result = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(payload));
  return [...new Uint8Array(result)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function liveFixture(): MissionBundle & { manifest: PresentationManifestV1 } {
  const fixture = createMissionBundleFixture();
  const { schema_version: _schema, ...legacy } = fixture.manifest;
  const generic = { ...legacy } as Record<string, unknown>;
  delete generic.demo_scenario;
  const manifest = {
    ...generic,
    schema_version: PRESENTATION_MANIFEST_SCHEMA,
    build_week_revision: null,
    battlestar_revision: null,
    run_mode: "LIVE",
    modeldock_mode: "NOT_RECORDED",
    modeldock_revision_or_service_identity: null,
    modeldock_provider: null,
    modeldock_model: null,
    modeldock_trace_id: null,
    generated_at: WHEN,
  } as PresentationManifestV1;
  const bundle = { ...fixture, manifest };
  bundle.snapshot.run_mode = "LIVE";
  bundle.snapshot.observed_at = WHEN;
  bundle.summary.run_mode = "LIVE";
  bundle.summary.generated_at = WHEN;
  bundle.summary.modeldock = { status: "NOT_RECORDED", provider: null, model: null, trace_id: null };
  bundle.captainsLog.run_mode = "LIVE";
  bundle.captainsLog.generated_at = WHEN;
  return bundle;
}

function recordedCall(bundle: MissionBundle, status: ModelDockCallContract["status"]): void {
  const call: ModelDockCallContract = {
    call_id: "call-live-test", status,
    mission_id: bundle.summary.mission_id, request_id: bundle.summary.request_id, run_mode: "LIVE",
    endpoint: "http://127.0.0.1:8000/text/generate", provider: status === "SUCCEEDED" ? "mlx" : null,
    model: status === "SUCCEEDED" ? "local-test-model" : null, model_revision: null,
    trace_id: status === "SUCCEEDED" ? "test-live-trace" : null,
    mocked: status === "SUCCEEDED" ? false : null, latency_ms: null,
    request_sha256: "a".repeat(64), response_sha256: status === "SUCCEEDED" ? "b".repeat(64) : null,
    response_byte_size: null, started_at: WHEN, observed_at: WHEN, artifacts: [], error: null,
  };
  bundle.snapshot.stages.oracle.modeldock_calls = [call];
  bundle.snapshot.components.modeldock = {
    run_mode: "LIVE", transport: "LIVE_HTTP", expected_provider: "mlx", replay_fixture_id: null,
    endpoint: call.endpoint,
  };
  bundle.summary.modeldock = { status, provider: call.provider, model: call.model, trace_id: call.trace_id };
  bundle.manifest.modeldock_mode = status === "SUCCEEDED" ? "LIVE" : status;
  bundle.manifest.modeldock_provider = call.provider;
  bundle.manifest.modeldock_model = call.model;
  bundle.manifest.modeldock_trace_id = call.trace_id;
}

/** Synthetic bytes only: never relabel a real replay artifact as LIVE. */
async function publication(
  change: (bundle: ReturnType<typeof liveFixture>) => void = () => {},
  sourceChange: (bundle: ReturnType<typeof liveFixture>) => void = () => {},
) {
  const bundle = liveFixture();
  change(bundle);
  const files = new Map<string, string>();
  async function reference(name: string, path: string, schema: string | null, payload: unknown) {
    const bytes = `${JSON.stringify(payload)}\n`;
    files.set(path, bytes);
    return { ...artifact(name, path, schema), sha256: await digest(bytes),
      byte_size: new TextEncoder().encode(bytes).byteLength, observed_at: WHEN };
  }
  bundle.manifest.final_snapshot = await reference("mission_snapshot", "mission_snapshot.json", bundle.snapshot.schema_version, bundle.snapshot);
  const immutablePath = `snapshots/mission_snapshot-r${String(bundle.snapshot.revision).padStart(4, "0")}.json`;
  files.set(immutablePath, files.get("mission_snapshot.json")!);
  const source = { ...bundle.manifest.final_snapshot, name: `mission_snapshot_r${String(bundle.snapshot.revision).padStart(4, "0")}`, path: immutablePath };
  bundle.summary.generated_from_snapshot = source;
  bundle.captainsLog.generated_from_snapshot = { ...source };
  sourceChange(bundle);
  bundle.manifest.mission_summary = await reference("mission_summary", "presentation/mission_summary.json", bundle.summary.schema_version, bundle.summary);
  bundle.manifest.captains_log = await reference("captains_log", "presentation/captains_log.json", bundle.captainsLog.schema_version, bundle.captainsLog);
  if (bundle.cabinContext) {
    bundle.manifest.cabin_context = await reference("cabin_context", "presentation/cabin_context.json", bundle.cabinContext.schema_version, bundle.cabinContext);
  }
  const manifestBytes = `${JSON.stringify(bundle.manifest)}\n`;
  files.set("presentation/manifest.json", manifestBytes);
  const id = await digest(manifestBytes);
  const feed: ReadyLiveMissionFeed = {
    schema_version: CABIN_FEED_SCHEMA, status: "READY", publication_id: id,
    base_url: `revisions/${id}/`, checked_at: WHEN, observed_at: WHEN,
    mission_id: bundle.summary.mission_id, message: "Canonical mission available.",
  };
  const fetchImpl = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const path = String(input);
    if (path === "/live/current.json") return new Response(JSON.stringify(feed));
    const prefix = `/live/${feed.base_url}`;
    if (!path.startsWith(prefix)) return new Response("Not found", { status: 404 });
    const content = files.get(path.slice(prefix.length));
    return content === undefined ? new Response("Not found", { status: 404 }) : new Response(content);
  });
  return { bundle, files, feed, fetchImpl: fetchImpl as typeof fetch & typeof fetchImpl };
}

async function catalogPublication(
  changeCatalog: (catalog: NavigatorCatalogV1) => void = () => {},
  changeMarket: (market: NavigatorMarket) => void = () => {},
) {
  const result = await publication();
  const { bundle, files, feed } = result;
  const market: NavigatorMarket = {
    symbol: bundle.summary.symbol, name: "Apple Inc.", category: "equity", timeframe: "1d", ma_period: 250, currency: "USD",
    data: { stale: false, age_seconds: 0, source: "provider", provider: "yfinance" },
    points: [
      { t: 100, o: 190, h: 192, l: 189, c: 191, v: 1000, ma: null, atr: null },
      { t: 200, o: 191, h: 194, l: 190, c: 193, v: 1200, ma: 188, atr: 3 },
    ],
    summary: { last_price: 193, last_ma: 188, pct_vs_ma: 2.6596, position: "above", trend_slope_pct: 0.5,
      volatility: "moderate", atr: 3, atr_pct: 1.5544, ma_period: 250, bar_count: 2 },
  };
  async function reference(name: string, path: string, schema: string, payload: unknown, producer: string, observed_at: string) {
    const bytes = `${JSON.stringify(payload)}\n`;
    files.set(path, bytes);
    return { name, path, schema_version: schema, producer, observed_at, sha256: await digest(bytes),
      byte_size: new TextEncoder().encode(bytes).byteLength };
  }
  const marketReference = await reference("navigator_market", "presentation/navigator_market.json", "navigator.api.ohlc.v1", market, "navigator", WHEN);
  bundle.cabinContext = {
    schema_version: "blackpod.cabin_context.v1", mission_id: bundle.summary.mission_id, request_id: bundle.summary.request_id,
    symbol: bundle.summary.symbol, run_mode: "LIVE", captured_at: WHEN, market_artifact: marketReference, portfolio_artifact: null,
    capture_provenance: {
      market: { status: "CAPTURED", transport: "HTTP", source_identity: "navigator-original-capture", navigator_git_revision: "a".repeat(40) },
      portfolio: { status: "NOT_CONFIGURED", transport: null, source_identity: null },
    },
  };
  bundle.manifest.cabin_context = await reference("cabin_context", "presentation/cabin_context.json",
    "blackpod.cabin_context.v1", bundle.cabinContext, "harbormaster", WHEN);
  const variant = structuredClone(market);
  variant.timeframe = "1h";
  variant.ma_period = variant.summary.ma_period = 20;
  changeMarket(variant);
  const variantTime = "2026-09-15T20:00:00Z";
  const catalogTime = "2026-09-15T21:00:00Z";
  const variantReference = await reference("navigator_market_variant", "presentation/navigator_variants/1h-ma20.json",
    "navigator.api.ohlc.v1", variant, "navigator", variantTime);
  const catalog: NavigatorCatalogV1 = {
    schema_version: "blackpod.navigator_catalog.v1", mission_id: bundle.summary.mission_id, request_id: bundle.summary.request_id,
    symbol: bundle.summary.symbol, run_mode: "LIVE", captured_at: catalogTime,
    entries: [{ timeframe: "1h", ma_period: 20, captured_at: variantTime, transport: "HTTP",
      source_identity: "navigator-variant-capture", navigator_git_revision: "b".repeat(40), artifact: variantReference }],
  };
  changeCatalog(catalog);
  bundle.manifest.navigator_catalog = await reference("navigator_catalog", "presentation/navigator_catalog.json",
    "blackpod.navigator_catalog.v1", catalog, "harbormaster", catalogTime);
  const manifestBytes = `${JSON.stringify(bundle.manifest)}\n`;
  files.set("presentation/manifest.json", manifestBytes);
  feed.publication_id = await digest(manifestBytes);
  feed.base_url = `revisions/${feed.publication_id}/`;
  return { ...result, market, variant, catalog };
}

describe("Navigator catalog publication loading", () => {
  it("loads exact variants and their own capture metadata without replacing the original market", async () => {
    const source = await catalogPublication();
    const loaded = await loadLiveMissionBundle(source.feed, { fetchImpl: source.fetchImpl });
    expect(loaded.navigatorMarket).toEqual(source.market);
    expect(loaded.cabinContext?.captured_at).toBe(WHEN);
    expect(loaded.navigatorVariants).toEqual([{
      market: source.variant, capturedAt: source.catalog.entries[0].captured_at,
      sourceIdentity: "navigator-variant-capture", navigatorGitRevision: "b".repeat(40),
      reference: source.catalog.entries[0].artifact,
    }]);
    expect(source.fetchImpl.mock.calls.every(([url]) => String(url).startsWith(`/live/${source.feed.base_url}`))).toBe(true);
  });

  it.each(["presentation/navigator_catalog.json", "presentation/navigator_variants/1h-ma20.json"])(
    "rejects missing or tampered declared %s instead of falling back", async (path) => {
      const source = await catalogPublication();
      source.files.set(path, `${source.files.get(path)} `);
      await expect(loadLiveMissionBundle(source.feed, { fetchImpl: source.fetchImpl })).rejects.toThrow(/byte size|SHA-256/);
      source.files.delete(path);
      await expect(loadLiveMissionBundle(source.feed, { fetchImpl: source.fetchImpl })).rejects.toThrow(/HTTP 404/);
    },
  );

  it("rejects capture-time disagreement even when catalog hashes verify", async () => {
    const source = await catalogPublication((catalog) => { catalog.captured_at = "2026-09-15T22:00:00Z"; });
    await expect(loadLiveMissionBundle(source.feed, { fetchImpl: source.fetchImpl })).rejects.toThrow(/capture time conflicts/);
  });

  it.each(["correlation", "duplicate variant", "duplicate default"])("rejects rehashed catalog %s", async (kind) => {
    const source = await catalogPublication((catalog) => {
      if (kind === "correlation") catalog.mission_id = "mission-other";
      if (kind === "duplicate variant") catalog.entries = [...catalog.entries, catalog.entries[0]];
      if (kind === "duplicate default") {
        catalog.entries[0].timeframe = "1d";
        catalog.entries[0].ma_period = 250;
      }
    });
    await expect(loadLiveMissionBundle(source.feed, { fetchImpl: source.fetchImpl })).rejects.toThrow(/correlation|duplicates/);
  });

  it("requires the original captured market, not just an empty bound context", async () => {
    const source = await catalogPublication();
    source.bundle.cabinContext!.market_artifact = null;
    source.bundle.cabinContext!.capture_provenance.market = {
      status: "NOT_CONFIGURED", transport: null, source_identity: null, navigator_git_revision: null,
    };
    const bytes = `${JSON.stringify(source.bundle.cabinContext)}\n`;
    source.files.set("presentation/cabin_context.json", bytes);
    source.bundle.manifest.cabin_context!.sha256 = await digest(bytes);
    source.bundle.manifest.cabin_context!.byte_size = new TextEncoder().encode(bytes).byteLength;
    const manifest = `${JSON.stringify(source.bundle.manifest)}\n`;
    source.files.set("presentation/manifest.json", manifest);
    source.feed.publication_id = await digest(manifest);
    source.feed.base_url = `revisions/${source.feed.publication_id}/`;
    await expect(loadLiveMissionBundle(source.feed, { fetchImpl: source.fetchImpl })).rejects.toThrow(/original captured market context/);
    expect(source.fetchImpl.mock.calls.some(([url]) => String(url).endsWith("navigator_catalog.json"))).toBe(false);
  });

  it.each(["timeframe", "MA", "symbol", "synthetic"])("rejects a rehashed %s mismatch in supplied variant bytes", async (kind) => {
    const source = await catalogPublication(undefined, (market) => {
      if (kind === "timeframe") market.timeframe = "1wk";
      if (kind === "MA") market.ma_period = market.summary.ma_period = 50;
      if (kind === "symbol") market.symbol = "MSFT";
      if (kind === "synthetic") market.data!.provider = "synthetic";
    });
    await expect(loadLiveMissionBundle(source.feed, { fetchImpl: source.fetchImpl })).rejects.toThrow(/conflicts|does not match|synthetic/);
  });

  it("rejects malformed manifest references and never accepts a catalog on replay manifests", async () => {
    const source = await catalogPublication();
    const original = source.bundle.manifest.navigator_catalog!;
    for (const changed of [
      { name: "other" }, { path: "presentation/other.json" }, { schema_version: "other" },
      { producer: "browser" }, { byte_size: null }, { observed_at: null },
    ]) {
      expect(() => parsePresentationManifest({ ...source.bundle.manifest, navigator_catalog: { ...original, ...changed } })).toThrow(/Navigator catalog/);
    }
    expect(() => parsePresentationManifest({ ...source.bundle.manifest, run_mode: "REPLAY" })).toThrow(/LIVE Navigator catalog/);
    const { cabin_context: _context, ...withoutContext } = source.bundle.manifest;
    expect(() => parsePresentationManifest(withoutContext)).toThrow(/LIVE Navigator catalog/);
  });
});

describe("live mission feed contract", () => {
  it("reads the same-origin pointer without cache and forwards cancellation", async () => {
    const { feed, fetchImpl } = await publication();
    const signal = new AbortController().signal;
    await expect(loadLiveMissionFeed({ fetchImpl, signal })).resolves.toEqual(feed);
    expect(fetchImpl).toHaveBeenCalledWith("/live/current.json", {
      cache: "no-store", headers: { Accept: "application/json" }, signal,
    });
  });

  it.each(["NOT_CONFIGURED", "UNAVAILABLE"] as const)("accepts honest %s without synthetic publication", (status) => {
    expect(parseLiveMissionFeed({ schema_version: CABIN_FEED_SCHEMA, status, checked_at: WHEN, message: "Not available." }))
      .toEqual({ schema_version: CABIN_FEED_SCHEMA, status, checked_at: WHEN, message: "Not available." });
  });

  it.each(["https://remote.example/data/", "//remote.example/data/", "../private/", "revisions/%2e%2e/", "revisions/other/"])(
    "rejects off-origin or mismatched publication path %s before fetching", async (base_url) => {
      const { feed, fetchImpl } = await publication();
      await expect(loadLiveMissionBundle({ ...feed, base_url }, { fetchImpl })).rejects.toThrow(/same-origin immutable/);
      expect(fetchImpl).not.toHaveBeenCalled();
    },
  );

  it("rejects unknown feed fields and malformed timestamps/statuses", async () => {
    const { feed } = await publication();
    expect(() => parseLiveMissionFeed({ ...feed, broker_url: "hidden" })).toThrow(/unknown fields/);
    expect(() => parseLiveMissionFeed({ ...feed, checked_at: "yesterday" })).toThrow(/ISO UTC/);
    expect(() => parseLiveMissionFeed({ ...feed, status: "APPROVED" })).toThrow(/unsupported live feed status/);
  });

  it("does not fallback to a demo after transport or invalid JSON failures", async () => {
    const unavailable = vi.fn(async () => new Response("missing", { status: 503 }));
    await expect(loadLiveMissionFeed({ fetchImpl: unavailable as typeof fetch })).rejects.toThrow(/503/);
    expect(unavailable).toHaveBeenCalledTimes(1);
    await expect(loadLiveMissionFeed({ fetchImpl: (async () => new Response("<html>")) as typeof fetch })).rejects.toThrow(/valid UTF-8 JSON/);
  });
});

describe("immutable live publication loading", () => {
  it("loads generic contracts with no ModelDock calls or market supplements and preserves unknown revisions", async () => {
    const { feed, fetchImpl } = await publication();
    const loaded = await loadLiveMissionBundle(feed, { fetchImpl });
    expect(loaded.manifest.schema_version).toBe(PRESENTATION_MANIFEST_SCHEMA);
    expect(loaded.manifest.build_week_revision).toBeNull();
    expect(loaded.navigatorMarket).toBeNull();
    expect(loaded.portfolio).toBeNull();
    expect(loaded.snapshot.run_mode).toBe("LIVE");
    expect(createMissionViewModel(loaded).revisions.battlestar).toBe("Not recorded");
    expect(createMissionViewModel(loaded).modeldock.availability).toBe("NO INFERENCE RECORDED");
    expect(fetchImpl.mock.calls.some(([url]) => String(url).includes("/demo/"))).toBe(false);
  });

  it.each(["HELD", "VETOED", "FAILED", "INCOMPLETE"] as const)("accepts canonical %s without approval or Navigator plan", async (outcome) => {
    const { feed, fetchImpl } = await publication((bundle) => {
      bundle.summary.final_outcome = outcome;
      bundle.manifest.final_outcome = outcome;
      bundle.snapshot.mission_outcome = outcome;
      bundle.summary.current_phase = "OPERATOR";
      bundle.snapshot.current_phase = "OPERATOR";
      bundle.summary.terminal = false;
      bundle.summary.resumable = true;
      bundle.snapshot.terminal = false;
      bundle.summary.operator = { route: "PENDING_APPROVAL", action_status: "NOT_STARTED", action: null, result: null };
      Object.assign(bundle.snapshot.operator, bundle.summary.operator, { action_id: null, operator_id: null, acted_at: null });
      bundle.summary.approval_scope = null;
      bundle.snapshot.approval_scope = null;
      bundle.snapshot.stages.navigator.status = "NOT_STARTED";
      bundle.snapshot.stages.navigator.native_state = null;
      bundle.summary.stages.navigator = { technical_status: "NOT_STARTED", native_state: null };
      bundle.summary.navigator = { technical_status: "NOT_STARTED", native_state: null, mode: null, handoff_status: null, intake_status: null, plan_status: null };
      Object.assign(bundle.snapshot.navigator, { mode: null, handoff_status: null, intake_status: null, plan_status: null,
        handoff_id: null, intake_receipt_id: null, plan_id: null, expires_at: null, idempotency_key: null,
        allowed_operations: [], prohibited_operations: [] });
    });
    const loaded = await loadLiveMissionBundle(feed, { fetchImpl });
    expect(loaded.summary.final_outcome).toBe(outcome);
    expect(loaded.summary.operator.result).toBeNull();
    expect(loaded.summary.navigator.plan_status).toBeNull();
  });

  it.each(["RUNNING", "FAILED", "SUCCEEDED"] as const)("accepts recorded ModelDock %s without implying current service health", async (status) => {
    const { feed, fetchImpl } = await publication((bundle) => recordedCall(bundle, status));
    const vm = createMissionViewModel(await loadLiveMissionBundle(feed, { fetchImpl }));
    expect(vm.modeldock.availability).toContain("AT MISSION TIME");
    expect(vm.modeldock.lastSuccessfulInference).toBe(status === "SUCCEEDED" ? WHEN : null);
  });

  it("loads original v1 snapshot bytes using the canonical optional-field defaults without changing their digest", async () => {
    const requestBytes = JSON.stringify({ symbol: "AAPL", mission_id: "mission-buildweek-replay-001" });
    const requestSha = await digest(requestBytes);
    const { feed, fetchImpl, bundle: source, files } = await publication((bundle) => {
      bundle.summary.final_outcome = bundle.snapshot.mission_outcome = bundle.manifest.final_outcome = "INCOMPLETE";
      bundle.summary.current_phase = bundle.snapshot.current_phase = "ORACLE";
      bundle.summary.terminal = bundle.snapshot.terminal = false;
      bundle.summary.resumable = true;
      bundle.summary.approval_scope = null;
      bundle.summary.governor_disposition = null;
      bundle.summary.operator = { route: null, action_status: "NOT_STARTED", action: null, result: null };
      bundle.summary.navigator = { technical_status: "NOT_STARTED", native_state: null, mode: null,
        handoff_status: null, intake_status: null, plan_status: null };
      for (const stage of ["oracle", "council", "governor", "navigator"] as const) {
        bundle.summary.stages[stage] = { technical_status: "NOT_STARTED", native_state: null };
        bundle.snapshot.stages[stage].status = "NOT_STARTED";
        bundle.snapshot.stages[stage].native_state = null;
      }
      const raw = bundle.snapshot as unknown as Record<string, unknown>;
      for (const field of ["components", "operator", "navigator", "approval_scope"]) delete raw[field];
      raw.artifacts = [{ name: "mission_request", path: "request/mission_request.json", sha256: requestSha }];
      raw.stages = Object.fromEntries(Object.entries(bundle.snapshot.stages)
        .map(([stage, state]) => [stage, { status: state.status, native_state: state.native_state }]));
    });
    files.set("request/mission_request.json", requestBytes);
    const loaded = await loadLiveMissionBundle(feed, { fetchImpl });
    expect(loaded.snapshot.components).toEqual({});
    expect(loaded.snapshot.operator.action_status).toBe("NOT_STARTED");
    expect(loaded.snapshot.navigator.allowed_operations).toEqual([]);
    expect(loaded.snapshot.approval_scope).toBeNull();
    expect(loaded.snapshot.stages.oracle.modeldock_calls).toEqual([]);
    expect(loaded.evidence.get("mission_request")?.status).toBe("LOADED");
    expect(loaded.snapshot.artifacts[0].byte_size).toBeNull();
    expect(loaded.manifest.final_snapshot.sha256).toBe(await digest(files.get("mission_snapshot.json")!));
    expect(loaded.manifest.final_snapshot.sha256).toBe(source.manifest.final_snapshot.sha256);
  });

  it("rejects changed manifest bytes even if the document still parses", async () => {
    const { feed, fetchImpl, files } = await publication();
    files.set("presentation/manifest.json", `${files.get("presentation/manifest.json")} `);
    await expect(loadLiveMissionBundle(feed, { fetchImpl })).rejects.toThrow(/manifest SHA-256/);
  });

  it("ignores undeclared optional files and never fetches their unbound bytes", async () => {
    const { feed, fetchImpl, files } = await publication();
    files.set("presentation/cabin_context.json", "{}");
    files.set("presentation/navigator_catalog.json", "{}");
    const loaded = await loadLiveMissionBundle(feed, { fetchImpl });
    expect(loaded.cabinContext).toBeNull();
    expect(loaded.navigatorVariants).toEqual([]);
    expect(fetchImpl.mock.calls.some(([url]) => String(url).endsWith("cabin_context.json"))).toBe(false);
    expect(fetchImpl.mock.calls.some(([url]) => String(url).endsWith("navigator_catalog.json"))).toBe(false);
  });

  it("hashes a declared optional wrapper and rejects missing or altered wrapper bytes", async () => {
    const { feed, fetchImpl, files } = await publication((bundle) => {
      bundle.cabinContext = {
        schema_version: "blackpod.cabin_context.v1",
        mission_id: bundle.summary.mission_id, request_id: bundle.summary.request_id,
        symbol: bundle.summary.symbol, run_mode: "LIVE", captured_at: WHEN,
        market_artifact: null, portfolio_artifact: null,
        capture_provenance: {
          market: { status: "NOT_CONFIGURED", transport: null, source_identity: null, navigator_git_revision: null },
          portfolio: { status: "NOT_CONFIGURED", transport: null, source_identity: null },
        },
      };
    });
    expect((await loadLiveMissionBundle(feed, { fetchImpl })).cabinContext?.captured_at).toBe(WHEN);
    files.set("presentation/cabin_context.json", "{}");
    await expect(loadLiveMissionBundle(feed, { fetchImpl })).rejects.toThrow(/cabin context byte size|cabin context SHA-256/);
    files.delete("presentation/cabin_context.json");
    await expect(loadLiveMissionBundle(feed, { fetchImpl })).rejects.toThrow(/cabin context returned HTTP 404/);
  });

  it("rejects unknown generic fields and does not accept a demo manifest on the live path", async () => {
    const { bundle } = await publication();
    expect(() => parsePresentationManifest({ ...bundle.manifest, demo_scenario: "approved" })).toThrow(/unknown demo_scenario/);
    expect(() => parsePresentationManifest(createMissionBundleFixture().manifest)).toThrow();
  });

  it("rejects changed primary or immutable bytes without using stale aliases", async () => {
    const primary = await publication();
    primary.files.set("presentation/mission_summary.json", "{}");
    await expect(loadLiveMissionBundle(primary.feed, { fetchImpl: primary.fetchImpl })).rejects.toThrow(/byte size|SHA-256/);
    const immutable = await publication();
    immutable.files.set(immutable.bundle.summary.generated_from_snapshot.path, "{}");
    await expect(loadLiveMissionBundle(immutable.feed, { fetchImpl: immutable.fetchImpl })).rejects.toThrow(/byte size|SHA-256/);
  });

  it("rejects latest-snapshot correlation conflicts even with recomputed primary hashes", async () => {
    const { feed, fetchImpl } = await publication(() => {}, (bundle) => {
      bundle.summary.generated_from_snapshot.path = "snapshots/mission_snapshot-r0012.json";
    });
    await expect(loadLiveMissionBundle(feed, { fetchImpl })).rejects.toThrow(/latest immutable snapshot/);
  });

  it("rejects mismatched feed mission identity and observed time", async () => {
    const { feed, fetchImpl } = await publication();
    await expect(loadLiveMissionBundle({ ...feed, mission_id: "wrong-mission" }, { fetchImpl })).rejects.toThrow(/feed pointer/);
    await expect(loadLiveMissionBundle({ ...feed, observed_at: "2026-09-14T19:00:00Z" }, { fetchImpl })).rejects.toThrow(/feed pointer/);
  });

  it("rejects replay missions on live transport", async () => {
    const { feed, fetchImpl } = await publication((bundle) => {
      bundle.manifest.run_mode = bundle.summary.run_mode = bundle.captainsLog.run_mode = bundle.snapshot.run_mode = "REPLAY";
    });
    await expect(loadLiveMissionBundle(feed, { fetchImpl })).rejects.toThrow(/REPLAY evidence/);
  });

  it.each(["mocked", "provider", "run_mode", "mission_id"] as const)("rejects false successful inference %s", async (field) => {
    const { feed, fetchImpl } = await publication((bundle) => {
      recordedCall(bundle, "SUCCEEDED");
      const call = bundle.snapshot.stages.oracle.modeldock_calls[0];
      if (field === "mocked") call.mocked = true;
      if (field === "provider") call.provider = "remote";
      if (field === "run_mode") call.run_mode = "REPLAY";
      if (field === "mission_id") call.mission_id = "other-mission";
    });
    await expect(loadLiveMissionBundle(feed, { fetchImpl })).rejects.toThrow(/nonmocked mlx provenance|LIVE mission correlation/);
  });

  it("rejects replay transport provenance despite a successful nonmocked call claim", async () => {
    const { feed, fetchImpl } = await publication((bundle) => {
      recordedCall(bundle, "SUCCEEDED");
      bundle.snapshot.components.modeldock.transport = "REPLAY_FIXTURE";
    });
    await expect(loadLiveMissionBundle(feed, { fetchImpl })).rejects.toThrow(/consistent LIVE_HTTP provenance/);
  });

  it("requires every known referenced detail artifact", async () => {
    const { feed, fetchImpl } = await publication((bundle) => {
      bundle.snapshot.artifacts.push(artifact("oracle_report", "oracle/report.json"));
    });
    await expect(loadLiveMissionBundle(feed, { fetchImpl })).rejects.toThrow(/evidence oracle_report returned HTTP 404/);
  });

  it("retains the explicit legacy replay loader and forwards signal to publication requests", async () => {
    const { feed, fetchImpl } = await publication();
    const signal = new AbortController().signal;
    await loadLiveMissionBundle(feed, { fetchImpl, signal });
    expect(fetchImpl.mock.calls.every(([, init]) => init?.signal === signal)).toBe(true);
    const legacyPack = await publication((bundle) => {
      bundle.manifest.run_mode = bundle.summary.run_mode = bundle.captainsLog.run_mode = bundle.snapshot.run_mode = "REPLAY";
    });
    const legacy = {
      ...legacyPack.bundle.manifest,
      schema_version: "blackpod.demo_manifest.v1", demo_scenario: "approved",
      build_week_revision: "a".repeat(40), battlestar_revision: "b".repeat(40), modeldock_mode: "REPLAYED",
    };
    legacyPack.files.set("presentation/demo_manifest.json", JSON.stringify(legacy));
    const requests: string[] = [];
    const legacyFetch = (async (input: RequestInfo | URL) => {
      requests.push(String(input));
      const content = legacyPack.files.get(String(input).replace("./demo/approved/", ""));
      return content === undefined ? new Response("missing", { status: 404 }) : new Response(content);
    }) as typeof fetch;
    expect((await loadMissionBundle(undefined, { fetchImpl: legacyFetch })).summary.run_mode).toBe("REPLAY");
    expect(requests[0]).toBe("./demo/approved/presentation/demo_manifest.json");
  });
});
