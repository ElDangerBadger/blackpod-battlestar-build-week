import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createMissionBundleFixture } from "./test/missionFixture";

vi.mock("./data/loadMission", async (importOriginal) => {
  const original = await importOriginal<typeof import("./data/loadMission")>();
  return {
    ...original,
    loadMissionBundle: vi.fn(async () => createMissionBundleFixture()),
  };
});

import App from "./App";
import { loadMissionBundle } from "./data/loadMission";

const mockedLoadMissionBundle = vi.mocked(loadMissionBundle);

function missionWithNavigatorMarket() {
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
      { t: 1_752_883_200, o: 213, h: 216, l: 212, c: 215, v: 48_000_000, ma: 202.2, atr: 4.1 },
    ],
    summary: {
      last_price: 215,
      last_ma: 202.2,
      pct_vs_ma: 6.33,
      position: "above",
      trend_slope_pct: 1.2,
      volatility: "gentle",
      atr: 4.1,
      atr_pct: 1.91,
      ma_period: 250,
      bar_count: 2,
    },
  };
  return bundle;
}

function liveMission() {
  const bundle = missionWithNavigatorMarket();
  bundle.summary.run_mode = "LIVE";
  bundle.captainsLog.run_mode = "LIVE";
  bundle.manifest.run_mode = "LIVE";
  bundle.manifest.modeldock_mode = "LIVE";
  bundle.snapshot.run_mode = "LIVE";
  bundle.snapshot.stages.oracle.modeldock_calls = [{
    call_id: "modeldock-live-001",
    status: "SUCCEEDED",
    mission_id: bundle.summary.mission_id,
    request_id: bundle.summary.request_id,
    run_mode: "LIVE",
    endpoint: "http://127.0.0.1:8000/text/generate",
    provider: "mlx",
    model: "demo-model",
    model_revision: "model-revision-001",
    trace_id: "trace-live-001",
    mocked: false,
    latency_ms: 911,
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

describe("Captain's Cabin", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
    mockedLoadMissionBundle.mockReset();
    mockedLoadMissionBundle.mockImplementation(async () => createMissionBundleFixture());
  });

  it("shows the canonical approval chain and SHADOW-only boundary", async () => {
    render(<App />);

    expect(await screen.findByText("APPROVED · COMPLETE")).toBeInTheDocument();
    expect(screen.getAllByText("NAVIGATOR_SHADOW_HANDOFF").length).toBeGreaterThan(0);
    expect(screen.getByText("APPROVED_FOR_HANDOFF")).toBeInTheDocument();
    expect(screen.getAllByText(/PROCEED is not approval/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Navigator SHADOW handoff only/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Oracle remains authoritative for facts/i)).toBeInTheDocument();
    expect(screen.getByText(/Not configured — no illustrative holdings shown/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Mission Brief", hidden: true })).toHaveAttribute(
      "href",
      "/demo/approved/presentation/mission_brief.html",
    );
    expect(screen.getByText("Rotate device")).toBeInTheDocument();
    expect(mockedLoadMissionBundle).toHaveBeenCalledWith("/demo/approved/");
    expect(screen.getAllByText("DEMO").length).toBeGreaterThan(0);
  });

  it("opens a stage book with keyboard-safe page navigation and returns to the desk", async () => {
    render(<App />);
    const oracleButton = await screen.findByRole("button", { name: "Open Oracle book" });

    fireEvent.click(oracleButton);
    expect(screen.getByRole("dialog", { name: "Oracle" })).toBeInTheDocument();
    expect(screen.getByText("Page 1 of 6")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Page 2 of 6")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Oracle" })).not.toBeInTheDocument());
  });

  it("restarts the presentation without changing the canonical outcome", async () => {
    render(<App />);
    expect(await screen.findByText("APPROVED · COMPLETE")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Restart" }));

    expect(screen.getByText("APPROVED · COMPLETE")).toBeInTheDocument();
    expect(screen.getByText("Ready to replay")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open Oracle book" })).not.toBeInTheDocument();
    expect(screen.getByText(/Navigator SHADOW handoff only/i)).toBeInTheDocument();
  });

  it("selects the prepared LIVE pack explicitly and never substitutes the demo pack after failure", async () => {
    window.history.replaceState(null, "", "/?mode=live");
    mockedLoadMissionBundle.mockRejectedValueOnce(new Error("live pack unavailable"));

    render(<App />);

    expect(await screen.findByText(/LIVE mission pack: live pack unavailable/)).toBeInTheDocument();
    expect(screen.getByText(/No alternate mode was substituted/)).toBeInTheDocument();
    expect(mockedLoadMissionBundle).toHaveBeenCalledTimes(1);
    expect(mockedLoadMissionBundle).toHaveBeenCalledWith("/demo/live/");
  });

  it("loads an explicitly selected, non-mocked canonical LIVE mission", async () => {
    mockedLoadMissionBundle.mockImplementation(async (baseUrl) => baseUrl === "/demo/live/" ? liveMission() : createMissionBundleFixture());
    render(<App />);
    await screen.findByText("APPROVED · COMPLETE");

    fireEvent.click(screen.getByRole("button", { name: "Live" }));

    expect(await screen.findByText("LIVE current mission")).toBeInTheDocument();
    expect(screen.getByLabelText("Presentation mode LIVE; canonical mission mode LIVE")).toBeInTheDocument();
    expect(screen.getByText("LOCAL INFERENCE VERIFIED AT MISSION TIME")).toBeInTheDocument();
    expect(mockedLoadMissionBundle).toHaveBeenCalledWith("/demo/live/");
  });

  it("renders the supplied Navigator market evidence in overview and expanded modes", async () => {
    mockedLoadMissionBundle.mockResolvedValue(missionWithNavigatorMarket());

    render(<App />);

    const openShip = await screen.findByRole("button", { name: "Open expanded Navigator ship view for AAPL" });
    expect(screen.getAllByText("AAPL").length).toBeGreaterThan(0);
    expect(screen.getAllByText("DEMO").length).toBeGreaterThan(0);
    expect(screen.getAllByText("REPLAY").length).toBeGreaterThan(0);
    expect(screen.getAllByText("$215.00").length).toBeGreaterThan(0);
    expect(screen.getAllByText("$202.20").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Apple Inc.").length).toBeGreaterThan(0);
    expect(screen.getByText(/Supplemental; not Oracle evidence/i)).toBeInTheDocument();
    expect(screen.getByText(/Market status: not recorded/i)).toBeInTheDocument();
    fireEvent.click(openShip);

    expect(screen.getByRole("dialog", { name: "Navigator Ship View" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zoom in" })).toBeInTheDocument();
    expect(screen.getAllByText(/Navigation levels not present/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Not Oracle evidence · SHADOW presentation only/i)).toBeInTheDocument();

    const returnButton = screen.getByRole("button", { name: "Return to bridge" });
    expect(returnButton).toHaveFocus();
    fireEvent.click(returnButton);
    expect(screen.queryByRole("dialog", { name: "Navigator Ship View" })).not.toBeInTheDocument();
    await waitFor(() => expect(openShip).toHaveFocus());

    fireEvent.click(openShip);
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Navigator Ship View" })).not.toBeInTheDocument());
    expect(openShip).toHaveFocus();
  });

  it("never presents a SHADOW plan when canonical Navigator plan state is absent", async () => {
    const bundle = createMissionBundleFixture();
    bundle.summary.navigator.mode = null;
    bundle.summary.navigator.plan_status = null;
    bundle.snapshot.navigator.mode = null;
    bundle.snapshot.navigator.plan_status = null;
    mockedLoadMissionBundle.mockResolvedValue(bundle);

    render(<App />);

    expect(await screen.findByText("No canonical Navigator SHADOW plan was created.")).toBeInTheDocument();
    expect(screen.queryByText("NO ORDER CREATED")).not.toBeInTheDocument();
    expect(screen.getByText("NO ORDER EXECUTION")).toBeInTheDocument();
  });
});
