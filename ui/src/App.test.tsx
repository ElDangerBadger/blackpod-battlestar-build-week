import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createMissionBundleFixture } from "./test/missionFixture";

vi.mock("./data/loadMission", async (importOriginal) => {
  const original = await importOriginal<typeof import("./data/loadMission")>();
  return {
    ...original,
    loadMissionBundle: vi.fn(async () => createMissionBundleFixture()),
  };
});

vi.mock("./data/liveMission", () => ({
  loadLiveMissionFeed: vi.fn(),
  loadLiveMissionBundle: vi.fn(),
}));

import App from "./App";
import { loadMissionBundle } from "./data/loadMission";
import { loadLiveMissionBundle, loadLiveMissionFeed } from "./data/liveMission";

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
    window.history.replaceState(null, "", "/?mode=replay");
    mockedLoadMissionBundle.mockReset();
    mockedLoadMissionBundle.mockImplementation(async () => createMissionBundleFixture());
    vi.mocked(loadLiveMissionFeed).mockReset();
    vi.mocked(loadLiveMissionBundle).mockReset();
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
      "./demo/approved/presentation/mission_brief.html",
    );
    expect(screen.getByText("Rotate device")).toBeInTheDocument();
    expect(screen.getByText("Navigator chart not configured.")).toBeInTheDocument();
    expect(screen.getByText("Recorded Governor disposition")).toBeInTheDocument();
    expect(document.querySelector(".route-line")).toBeNull();
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

  it("defaults to the live reader and never substitutes a demo after failure", async () => {
    window.history.replaceState(null, "", "/");
    vi.mocked(loadLiveMissionFeed).mockRejectedValueOnce(new Error("reader unavailable"));

    render(<App />);

    expect(await screen.findByText("Live mission evidence unavailable.")).toBeInTheDocument();
    expect(screen.getByText(/No replay data is substituted/)).toBeInTheDocument();
    expect(mockedLoadMissionBundle).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Demo" })).not.toBeInTheDocument();
  });

  it("loads verified LIVE evidence by default without replay or mutation controls", async () => {
    window.history.replaceState(null, "", "/");
    const bundle = liveMission();
    bundle.baseUrl = `/live/revisions/${"a".repeat(64)}/`;
    vi.mocked(loadLiveMissionFeed).mockResolvedValue({ schema_version: "blackpod.cabin_feed.v1", status: "READY",
      checked_at: new Date().toISOString(), observed_at: bundle.snapshot.observed_at, message: "Verified mission",
      mission_id: bundle.summary.mission_id, publication_id: "a".repeat(64), base_url: `revisions/${"a".repeat(64)}/` });
    vi.mocked(loadLiveMissionBundle).mockResolvedValue(bundle);
    render(<App />);
    await screen.findByText("APPROVED · COMPLETE");

    expect(screen.getByText("Read-only · reader connected")).toBeInTheDocument();
    expect(screen.getByText("STALE EVIDENCE")).toBeInTheDocument();
    expect(screen.getByText("LOCAL INFERENCE VERIFIED AT MISSION TIME")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Restart" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Demo" })).not.toBeInTheDocument();
    expect(mockedLoadMissionBundle).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "Open Mission Brief", hidden: true })).toHaveAttribute("href", `${bundle.baseUrl}presentation/mission_brief.html`);
  });

  it("explains explicit source configuration instead of showing sample holdings", async () => {
    window.history.replaceState(null, "", "/");
    vi.mocked(loadLiveMissionFeed).mockResolvedValue({ schema_version: "blackpod.cabin_feed.v1", status: "NOT_CONFIGURED",
      checked_at: new Date().toISOString(), message: "Select a mission source." });
    render(<App />);
    expect(await screen.findByText("No live mission configured.")).toBeInTheDocument();
    expect(screen.getByText(/make cabin-live CABIN_ARTIFACTS_ROOT/)).toBeInTheDocument();
    expect(loadLiveMissionBundle).not.toHaveBeenCalled();
    expect(mockedLoadMissionBundle).not.toHaveBeenCalled();
  });

  it("renders the supplied Navigator market evidence in overview and expanded modes", async () => {
    mockedLoadMissionBundle.mockResolvedValue(missionWithNavigatorMarket());

    render(<App />);

    const openShip = await screen.findByRole("button", { name: "Open Navigator ship view for AAPL" });
    expect(screen.getAllByText("Apple Inc.").length).toBeGreaterThan(0);
    expect(screen.getByText(/Supplemental; not Oracle evidence/i)).toBeInTheDocument();
    expect(screen.getByText(/Market status: not recorded/i)).toBeInTheDocument();
    fireEvent.click(openShip);

    expect(screen.getByRole("dialog", { name: "Navigator Ship View" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zoom in" })).toBeInTheDocument();
    expect(screen.getAllByText(/Navigation levels not present/).length).toBeGreaterThan(0);
    expect(screen.getByText(/3D ocean unavailable; canonical chart shown/i)).toBeInTheDocument();
    expect(screen.getByText(/Latest captured bar:/i)).toBeInTheDocument();
    expect(screen.getByText(/Not Oracle evidence · SHADOW presentation only/i)).toBeInTheDocument();
  });

  it("closes the expanded Navigator with Escape and restores focus to its overview", async () => {
    mockedLoadMissionBundle.mockResolvedValue(missionWithNavigatorMarket());
    render(<App />);

    const openShip = await screen.findByRole("button", { name: "Open Navigator ship view for AAPL" });
    const liveButton = screen.getByRole("button", { name: "Live" });
    const restartButton = screen.getByRole("button", { name: "Restart" });
    expect(openShip).toHaveAttribute("aria-haspopup", "dialog");
    expect(openShip).toHaveAttribute("aria-expanded", "false");
    openShip.focus();
    fireEvent.click(openShip);
    const dialog = screen.getByRole("dialog", { name: "Navigator Ship View" });
    expect(dialog).toBeInTheDocument();
    expect(openShip).toHaveAttribute("aria-expanded", "true");
    expect(openShip.closest("[inert]")).not.toBeNull();
    expect(liveButton.closest("[inert]")).not.toBeNull();
    expect(restartButton.closest("[inert]")).not.toBeNull();
    expect(dialog.closest("[inert]")).toBeNull();
    expect(screen.queryByRole("button", { name: "Live" })).not.toBeInTheDocument();

    const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(
      'button:not([disabled]):not([tabindex="-1"]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ));
    const first = focusable[0];
    const last = focusable.at(-1);
    if (!first || !last) throw new Error("Navigator dialog must expose focusable controls");
    expect(first).toHaveTextContent("Return to bridge");
    last.focus();
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(first).toHaveFocus();
    first.focus();
    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
    expect(last).toHaveFocus();

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Navigator Ship View" })).not.toBeInTheDocument());
    await waitFor(() => expect(openShip).toHaveFocus());
    expect(openShip.closest("[inert]")).toBeNull();
    expect(openShip).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: "Live" })).toBe(liveButton);
  });

  it.each([
    { trigger: "Open Oracle book", dialog: "Oracle", close: "Return to full cabin" },
    { trigger: "Focus mission warnings", dialog: "Mission warnings", close: "Return to bridge" },
    { trigger: "Open Navigator reference tape", dialog: "Navigator reference tape", close: "Return to bridge" },
  ])("isolates the $dialog dialog and restores its trigger on close", async ({ trigger, dialog: name, close }) => {
    render(<App />);
    const opener = await screen.findByRole("button", { name: trigger });
    // A pointer click may leave focus on another control in Safari.
    screen.getByRole("button", { name: "Live" }).focus();
    fireEvent.click(opener);
    const dialog = screen.getByRole("dialog", { name });
    const closeButton = screen.getByRole("button", { name: close });
    expect(closeButton).toHaveFocus();
    expect(opener.closest("[inert]")).not.toBeNull();
    expect(dialog.closest("[inert]")).toBeNull();

    // jsdom has no native inert behavior; the focus guard also contains
    // unexpected programmatic focus while the dialog is open.
    opener.focus();
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
    fireEvent.click(closeButton);
    await waitFor(() => expect(screen.queryByRole("dialog", { name })).not.toBeInTheDocument());
    expect(opener).toHaveFocus();
    expect(opener.closest("[inert]")).toBeNull();
  });

  it("expands the reference tape and opens full Navigator without changing its captured facts", async () => {
    mockedLoadMissionBundle.mockResolvedValue(missionWithNavigatorMarket());
    render(<App />);
    const opener = await screen.findByRole("button", { name: "Open Navigator reference tape" });
    expect(opener).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(opener);
    const tape = screen.getByRole("dialog", { name: "Navigator reference tape" });
    expect(opener).toHaveAttribute("aria-expanded", "true");
    expect(within(tape).getByText("$215.00")).toBeInTheDocument();
    expect(within(tape).getByText("$202.20")).toBeInTheDocument();
    expect(within(tape).getByText(/This is the mission's original captured price reference/)).toBeInTheDocument();
    fireEvent.click(within(tape).getByRole("button", { name: "Open full Navigator" }));
    expect(screen.queryByRole("dialog", { name: "Navigator reference tape" })).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Navigator Ship View" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(opener).toHaveFocus());
    expect(opener).toHaveAttribute("aria-expanded", "false");
    expect(mockedLoadMissionBundle).toHaveBeenCalledTimes(1);
  });

  it("explains missing market evidence in the expanded tape without offering a substitute chart", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Open Navigator reference tape" }));
    const tape = screen.getByRole("dialog", { name: "Navigator reference tape" });
    expect(within(tape).getByText("No captured market reference is attached to this mission.")).toBeInTheDocument();
    expect(within(tape).queryByRole("button", { name: "Open full Navigator" })).not.toBeInTheDocument();
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
