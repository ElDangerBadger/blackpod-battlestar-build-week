import { describe, expect, it } from "vitest";
import { createMissionBundleFixture } from "../test/missionFixture";
import { createMissionViewModel } from "./viewModel";

function createStageFourBundle() {
  const bundle = createMissionBundleFixture();
  bundle.navigatorMarket = {
    symbol: "AAPL",
    name: "Apple Inc.",
    category: "equity",
    timeframe: "1d",
    ma_period: 250,
    currency: "USD",
    points: [
      { t: 1_752_796_800, o: 210, h: 214, l: 209, c: 213, v: 50_000_000, ma: 202, atr: 4 },
    ],
    summary: {
      last_price: 213,
      last_ma: 202,
      pct_vs_ma: 5.45,
      position: "above",
      trend_slope_pct: 1.2,
      volatility: "gentle",
      atr: 4,
      atr_pct: 1.88,
      ma_period: 250,
      bar_count: 1,
    },
  };
  bundle.portfolio = {
    schema_version: "blackpod.portfolio_snapshot.v1",
    captured_at: "2026-07-18T18:07:00Z",
    source_identity: "build-week-read-only-snapshot",
    mode: "FROZEN",
    account_type: "SHADOW",
    currency: "USD",
    positions: [],
  };
  bundle.snapshot.stages.oracle.modeldock_calls = [{
    call_id: "modeldock-call-001",
    status: "SUCCEEDED",
    mission_id: bundle.summary.mission_id,
    request_id: bundle.summary.request_id,
    run_mode: "REPLAY",
    endpoint: "http://127.0.0.1:8000/text/generate",
    provider: "mlx",
    model: "demo-model",
    model_revision: "model-revision-001",
    trace_id: "trace-001",
    mocked: false,
    latency_ms: 842,
    request_sha256: "d".repeat(64),
    response_sha256: "e".repeat(64),
    response_byte_size: 512,
    started_at: "2026-07-18T18:06:00Z",
    observed_at: "2026-07-18T18:06:01Z",
    artifacts: ["oracle_modeldock_narrative"],
    error: null,
  }];
  return bundle;
}

describe("mission presentation view model", () => {
  it("projects canonical values without changing outcome or approval scope", () => {
    const viewModel = createMissionViewModel(createMissionBundleFixture());

    expect(viewModel.status.governorDisposition).toBe("PROCEED");
    expect(viewModel.status.operatorResult).toBe("APPROVED_FOR_HANDOFF");
    expect(viewModel.status.navigatorPlanStatus).toBe("CREATED");
    expect(viewModel.status.outcome).toBe("APPROVED");
    expect(viewModel.status.approvalScope).toBe("NAVIGATOR_SHADOW_HANDOFF");
  });

  it("preserves the exact SHADOW safety boundary and log order", () => {
    const viewModel = createMissionViewModel(createMissionBundleFixture());

    expect(viewModel.safety.displayStatement).toMatch(/SHADOW handoff only/);
    expect(viewModel.safety.allowedOperations).toEqual(["VALIDATE", "PLAN_ONLY"]);
    expect(viewModel.safety.prohibitedOperations).toEqual([
      "SUBMIT_ORDER",
      "CANCEL_ORDER",
      "MODIFY_PORTFOLIO",
      "BROKER_CALL",
    ]);
    expect(viewModel.captainsLog.map((entry) => entry.stage)).toEqual([
      "HARBORMASTER",
      "ORACLE",
      "MODELDOCK",
      "COUNCIL",
      "GOVERNOR",
      "OPERATOR",
      "NAVIGATOR",
      "MISSION",
    ]);
  });

  it("projects optional read-only market, portfolio, and recorded inference evidence without inventing market state", () => {
    const viewModel = createMissionViewModel(createStageFourBundle());

    expect(viewModel.market.companyName).toBe("Apple Inc.");
    expect(viewModel.market.timeframe).toBe("1d");
    expect(viewModel.market.latestCompletedBar).toBe("2025-07-18T00:00:00.000Z");
    expect(viewModel.market.marketStatus).toBeNull();
    expect(viewModel.market.regime).toBeNull();
    expect(viewModel.market.navigatorMarket?.summary.last_price).toBe(213);
    expect(viewModel.portfolio.status).toBe("CAPTURED");
    expect(viewModel.portfolio.mode).toBe("FROZEN");
    expect(viewModel.portfolio.activeExposure).toMatchObject({
      status: "NO_POSITION",
      symbol: "AAPL",
      direction: null,
      quantity: null,
      marketValue: null,
      allocationPercent: null,
      cash: null,
      equity: null,
      totalExposure: null,
    });
    expect(viewModel.modeldock.latencyMs).toBe(842);
    expect(viewModel.modeldock.lastSuccessfulInference).toBe("2026-07-18T18:06:01Z");
    expect(viewModel.modeldock.availability).toBe("FROZEN INFERENCE PROVENANCE");
  });

  it("projects an active-symbol position and optional portfolio totals exactly as supplied", () => {
    const bundle = createStageFourBundle();
    bundle.portfolio = {
      ...bundle.portfolio!,
      cash: 12_345.67,
      equity: 98_765.43,
      total_exposure: 86_419.76,
      positions: [
        {
          symbol: "MSFT",
          quantity: 4,
          market_value: 1_800,
          allocation_percent: 1.82,
        },
        {
          symbol: "AAPL",
          name: "Apple Inc.",
          quantity: -12.5,
          market_value: -4_171.75,
          allocation_percent: 4.224,
          cost_basis: 3_900.25,
          unrealized_pnl: -271.5,
        },
      ],
    };

    const exposure = createMissionViewModel(bundle).portfolio.activeExposure;

    expect(exposure).toEqual({
      status: "POSITION",
      symbol: "AAPL",
      direction: "SHORT",
      quantity: -12.5,
      marketValue: -4_171.75,
      allocationPercent: 4.224,
      costBasis: 3_900.25,
      unrealizedPnl: -271.5,
      cash: 12_345.67,
      equity: 98_765.43,
      totalExposure: 86_419.76,
      currency: "USD",
      capturedAt: "2026-07-18T18:07:00Z",
      mode: "FROZEN",
      sourceIdentity: "build-week-read-only-snapshot",
    });
  });

  it("keeps an absent portfolio source distinct from a captured snapshot with no active position", () => {
    const bundle = createMissionBundleFixture();
    const exposure = createMissionViewModel(bundle).portfolio.activeExposure;

    expect(exposure).toEqual({
      status: "NOT_CONFIGURED",
      symbol: "AAPL",
      direction: null,
      quantity: null,
      marketValue: null,
      allocationPercent: null,
      costBasis: null,
      unrealizedPnl: null,
      cash: null,
      equity: null,
      totalExposure: null,
      currency: null,
      capturedAt: null,
      mode: null,
      sourceIdentity: null,
    });
  });

  it("does not infer portfolio direction when a captured position omits quantity", () => {
    const bundle = createStageFourBundle();
    bundle.portfolio = {
      ...bundle.portfolio!,
      positions: [{ symbol: "AAPL", market_value: 2_500 }],
    };

    expect(createMissionViewModel(bundle).portfolio.activeExposure).toMatchObject({
      status: "POSITION",
      symbol: "AAPL",
      direction: null,
      quantity: null,
      marketValue: 2_500,
      allocationPercent: null,
    });
  });
});
