import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PORTFOLIO_SNAPSHOT_SCHEMA, type NavigatorMarket } from "../contracts/cabinContext";
import type { JsonObject } from "../contracts/presentation";
import type { MissionEvidenceName } from "../data/loadMission";
import { createMissionViewModel, type MissionViewModel } from "../data/viewModel";
import { artifact, createMissionBundleFixture } from "../test/missionFixture";
import { CABIN_PANEL_TITLES, CabinPanelDetails } from "./CabinPanelDetails";
import type { CabinPanelId } from "./cabinPanelTypes";

function mission(): MissionViewModel {
  return createMissionViewModel(createMissionBundleFixture());
}

function withEvidence(view: MissionViewModel, name: MissionEvidenceName, document: JsonObject) {
  const evidence = new Map(view.evidence);
  const reference = artifact(name, `recorded evidence/${name}.json`);
  evidence.set(name, { name, reference, document, status: "LOADED", message: null });
  return { ...view, evidence };
}

function fact(label: string): HTMLElement {
  return screen.getByText(label, { selector: "dt" }).nextElementSibling as HTMLElement;
}

function withMarket(): MissionViewModel {
  const view = mission();
  const market: NavigatorMarket = {
    symbol: "AAPL", name: "Apple Inc.", category: "equity", timeframe: "1d", ma_period: 250, currency: "USD",
    points: [{ t: 1789516800, o: 329, h: 334, l: 328, c: 331.34, v: 100, ma: 280.11, atr: 4 }],
    summary: { last_price: 331.34, last_ma: 280.11, pct_vs_ma: 18.29, position: "above", trend_slope_pct: 1, volatility: "high", atr: 4, atr_pct: 1.2, ma_period: 250, bar_count: 1 },
    data: { provider: "yfinance", source: "provider", stale: false, age_seconds: 0 },
  };
  return { ...view, market: { ...view.market, status: "CAPTURED", navigatorMarket: market,
    capturedAt: "2026-09-15T22:36:41Z", latestCompletedBar: "2026-09-15T00:00:00Z",
    marketStatus: null, sourceIdentity: "recorded-reference", artifactReference: artifact("navigator_market", "presentation/navigator_market.json"),
  } };
}

describe("CabinPanelDetails", () => {
  it("provides all fourteen requested read-only modules and handles missing optional evidence", () => {
    expect(Object.keys(CABIN_PANEL_TITLES)).toEqual([
      "market", "fleet", "modeldock", "timeframe", "mission", "market-timing", "mission-time",
      "approval", "watchlist", "governance", "governor", "portfolio", "model-routing", "safety",
    ]);
    const { container, rerender } = render(<CabinPanelDetails panel="market" mission={mission()} />);
    for (const panel of Object.keys(CABIN_PANEL_TITLES) as CabinPanelId[]) {
      rerender(<CabinPanelDetails panel={panel} mission={mission()} />);
      expect(container.querySelector(`.cabin-panel-details-${panel}`)).toBeInTheDocument();
      expect(container.textContent?.trim().length).toBeGreaterThan(40);
      if (panel === "watchlist") {
        expect(screen.getByRole("region", { name: "Local watchlist" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Add symbol" })).toBeInTheDocument();
      } else {
        expect(screen.queryByRole("region", { name: "Local watchlist" })).not.toBeInTheDocument();
        expect(screen.queryByRole("button")).not.toBeInTheDocument();
      }
    }
  });

  it("opens local preferences separately from the fleet record", () => {
    const onOpenWatchlist = vi.fn();
    render(<CabinPanelDetails panel="fleet" mission={mission()} onOpenWatchlist={onOpenWatchlist} />);
    expect(screen.queryByRole("region", { name: "Local watchlist" })).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Recorded fleet overview" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Manage local watchlist" }));
    expect(onOpenWatchlist).toHaveBeenCalledOnce();
  });

  it("separates Oracle market assessment from the mission and Navigator symbol", () => {
    const view = withEvidence(withMarket(), "oracle_assessment", {
      breadth_posture: "CONTRACTING_BREADTH", leadership_posture: "MIXED_LEADERSHIP",
      rotation_posture: "MIXED_ROTATION", risk_regime_posture: "NEW_UNKNOWN_VALUE",
    });
    render(<CabinPanelDetails panel="market" mission={view} />);
    expect(fact("Mission symbol")).toHaveTextContent("AAPL");
    expect(fact("Navigator reference")).toHaveTextContent("AAPL · Apple Inc.");
    expect(screen.getByText(/Market participation is contracting/)).toBeInTheDocument();
    expect(screen.getByText(/Recorded as “NEW_UNKNOWN_VALUE”. No plain-language interpretation/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "oracle_assessment.json" })).toHaveAttribute("href", "./demo/approved/recorded%20evidence/oracle_assessment.json");
    expect(screen.getByRole("link", { name: "navigator_market.json" })).toHaveAttribute("href", "./demo/approved/presentation/navigator_market.json");
  });

  it("does not invent source links when there is no exact recorded reference", () => {
    render(<CabinPanelDetails panel="mission" mission={mission()} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText("No original-artifact link is recorded for this panel.")).toBeInTheDocument();
  });

  it("identifies saved ModelDock provenance without implying a current health check", () => {
    const view = mission();
    view.modeldock = { ...view.modeldock, provider: "mlx", model: "full-model-name-not-truncated", traceId: "full-trace-id-not-truncated", latencyMs: 0, mocked: false, lastSuccessfulInference: "2026-09-15T23:05:00Z" };
    render(<CabinPanelDetails panel="modeldock" mission={view} />);
    expect(fact("Model")).toHaveTextContent("full-model-name-not-truncated");
    expect(fact("Trace ID")).toHaveTextContent("full-trace-id-not-truncated");
    expect(fact("Recorded latency")).toHaveTextContent("0 ms");
    expect(fact("Mocked")).toHaveTextContent("No");
    expect(fact("Last successful inference in this record")).toHaveTextContent("Sep 15, 2026, 11:05:00 PM UTC");
    expect(screen.getByText(/does not contact ModelDock, test a model, or request new commentary/)).toBeInTheDocument();
  });

  it("keeps absent model metadata unknown rather than zero or healthy", () => {
    const view = mission();
    view.modeldock = { ...view.modeldock, latencyMs: null, mocked: null, lastSuccessfulInference: null };
    render(<CabinPanelDetails panel="modeldock" mission={view} />);
    expect(fact("Recorded latency")).toHaveTextContent("Not recorded");
    expect(fact("Mocked")).toHaveTextContent("Not recorded");
    expect(fact("Last successful inference in this record")).toHaveTextContent("Not recorded");
  });

  it("distinguishes price bars from workflow snapshots without claiming unsupported intervals", () => {
    render(<CabinPanelDetails panel="timeframe" mission={withMarket()} />);
    expect(fact("Original chart bar interval")).toHaveTextContent("Daily · 1d");
    expect(fact("Original supplied price bars")).toHaveTextContent("1");
    expect(fact("Mission snapshots")).toHaveTextContent("13");
    expect(fact("Original supplied moving average")).toHaveTextContent("MA250 · 250 bars");
    expect(screen.getByText(/does not acquire finer bars or calculate a new moving average/)).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("keeps capture time separate from the latest bar and current market status", () => {
    render(<CabinPanelDetails panel="market-timing" mission={withMarket()} />);
    expect(fact("Capture time")).toHaveTextContent("Sep 15, 2026, 10:36:41 PM UTC");
    expect(fact("Latest supplied bar timestamp")).toHaveTextContent("Sep 15, 2026, 12:00:00 AM UTC");
    expect(fact("Recorded market status")).toHaveTextContent("Not recorded");
    expect(screen.getByText(/Refreshing the display does not acquire new price bars/)).toBeInTheDocument();
  });

  it("keeps the three mission timestamps separately labelled with exact originals", () => {
    const view = mission();
    view.status = { ...view.status, startedAt: "2026-09-15T23:00:00Z", observedAt: "2026-09-15T23:05:00Z", generatedAt: "2026-09-15T23:06:00Z" };
    render(<CabinPanelDetails panel="mission-time" mission={view} />);
    expect(fact("Mission started")).toHaveTextContent("11:00:00 PM UTC");
    expect(fact("Snapshot observed")).toHaveTextContent("11:05:00 PM UTC");
    expect(fact("Summary generated")).toHaveTextContent("11:06:00 PM UTC");
    expect(fact("Observed")).toHaveTextContent("2026-09-15T23:05:00Z");
  });

  it("does not infer operator authority from Governor or mission success", () => {
    const view = mission();
    view.status = { ...view.status, approvalScope: null, operatorRoute: null, operatorResult: null };
    render(<CabinPanelDetails panel="approval" mission={view} />);
    expect(fact("Approval scope")).toHaveTextContent("Not recorded");
    expect(fact("Operator result")).toHaveTextContent("Not recorded");
    expect(screen.getByText(/does not substitute for an operator approval/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows completed processes and blocked results as distinct governance facts", () => {
    let view = mission();
    view.stages.council = { ...view.stages.council, technicalStatus: "SUCCEEDED", nativeState: "BLOCKED" };
    view.stages.governor = { ...view.stages.governor, technicalStatus: "SUCCEEDED", nativeState: "BLOCKED" };
    view.status = { ...view.status, governorDisposition: "BLOCKED", outcome: "HELD", operatorResult: null };
    view = withEvidence(view, "governor_rendered_decision", { disposition: "BLOCKED", allowed_next_step: "NONE", blocking_reasons: ["mandate:READ_ONLY_DATA_RUN_NO_TRADING_AUTHORITY"] });
    render(<CabinPanelDetails panel="governance" mission={view} />);
    expect(fact("Council process")).toHaveTextContent("Process completed · SUCCEEDED");
    expect(fact("Council native result")).toHaveTextContent("BLOCKED");
    expect(fact("Governor process")).toHaveTextContent("Process completed · SUCCEEDED");
    expect(fact("Mission outcome")).toHaveTextContent("HELD");
    expect(fact("Operator result")).toHaveTextContent("Not recorded");
    expect(screen.getByText(/explicit analysis-only mandate with no trading authority/)).toBeInTheDocument();
  });

  it("does not infer an analysis-only mandate from a similar or unknown code", () => {
    const view = mission();
    view.warnings = ["UNKNOWN_READ_ONLY_DATA_RUN_NO_TRADING_AUTHORITY_REASON"];
    render(<CabinPanelDetails panel="governor" mission={view} />);
    expect(screen.queryByText(/This mission records an explicit analysis-only mandate/)).not.toBeInTheDocument();
  });

  it("uses only supplied portfolio fields and retains zero values and recorded currency", () => {
    const view = mission();
    view.portfolio = { ...view.portfolio, status: "CAPTURED", snapshot: {
      schema_version: PORTFOLIO_SNAPSHOT_SCHEMA, captured_at: "2026-09-15T22:00:00Z", source_identity: "recorded-portfolio",
      mode: "LIVE", account_type: "paper", currency: "CAD", cash: 0,
      positions: [{ symbol: "AAA", name: "Recorded position", quantity: 0, market_value: 123.45, allocation_percent: 0 }, { symbol: "BBB" }],
    } };
    const before = JSON.stringify(view.portfolio);
    render(<CabinPanelDetails panel="portfolio" mission={view} />);
    expect(fact("Recorded cash")).toHaveTextContent("0 CAD");
    expect(fact("Market value")).toHaveTextContent("123.45 CAD");
    expect(fact("Recorded allocation")).toHaveTextContent("0%");
    expect(screen.queryByText("Recorded total exposure")).not.toBeInTheDocument();
    expect(screen.queryByText("Recorded equity")).not.toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Captured position BBB" })).getByText(/No quantity or valuation fields were supplied/)).toBeInTheDocument();
    expect(JSON.stringify(view.portfolio)).toBe(before);
  });

  it("treats absent holdings as unknown, not an empty zero-value portfolio", () => {
    render(<CabinPanelDetails panel="portfolio" mission={mission()} />);
    expect(screen.getByText(/Holdings, cash, exposure, and account value are unknown/)).toBeInTheDocument();
    expect(screen.queryByText("0 USD")).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /Captured position/ })).not.toBeInTheDocument();
  });

  it("preserves exact allowed and prohibited operations and explains unknowns without inventing authority", () => {
    const view = mission();
    view.safety = { ...view.safety, allowedOperations: ["VALIDATE", "PLAN_ONLY"], prohibitedOperations: ["SUBMIT_ORDER", "BROKER_CALL", "UNKNOWN_OPERATION"] };
    render(<CabinPanelDetails panel="safety" mission={view} />);
    expect(screen.getByText("PLAN_ONLY", { selector: "code" })).toBeInTheDocument();
    expect(screen.getByText("SUBMIT_ORDER", { selector: "code" })).toBeInTheDocument();
    expect(screen.getByText("BROKER_CALL", { selector: "code" })).toBeInTheDocument();
    expect(screen.getByText(/No plain-language interpretation is defined for this recorded operation/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("only opens the requested ledger when a read-only deep-dive handler is supplied", () => {
    const onOpenBook = vi.fn();
    render(<CabinPanelDetails panel="model-routing" mission={mission()} onOpenBook={onOpenBook} />);
    fireEvent.click(screen.getByRole("button", { name: "Read the Oracle ledger" }));
    expect(onOpenBook).toHaveBeenCalledExactlyOnceWith("oracle");
    expect(screen.getByText(/cannot choose a model, route a new request, or call a provider/)).toBeInTheDocument();
  });
});
