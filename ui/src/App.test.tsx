import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { artifact, createMissionBundleFixture } from "./test/missionFixture";

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
import { CABIN_PANEL_TITLES } from "./components/CabinPanelDetails";
import type { CabinPanelId } from "./components/cabinPanelTypes";
import { loadMissionBundle } from "./data/loadMission";
import { loadLiveMissionBundle, loadLiveMissionFeed } from "./data/liveMission";
import { LOCAL_WATCHLIST_KEY } from "./data/localWatchlist";

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

function liveMissionWithFleetCaptures() {
  const bundle = liveMission();
  const original = bundle.navigatorMarket!;
  const capturedAt = "2026-09-16T14:00:00Z";
  const rows = [
    { symbol: "XLK", name: "Technology Select Sector SPDR Fund", price: 183.74, ma: 180, pct: 2.08 },
    { symbol: "SPY", name: "SPDR S&P 500 ETF Trust", price: 550.25, ma: 520, pct: 5.82 },
  ];
  const fleetReference = {
    ...artifact("oracle_normalized_snapshot", "oracle/fleet-normalized.json"),
    producer: "oracle",
  };
  bundle.evidence = new Map(bundle.evidence).set("oracle_normalized_snapshot", {
    name: "oracle_normalized_snapshot",
    reference: fleetReference,
    status: "LOADED",
    message: null,
    document: {
      normalized_snapshot_id: "fleet-snapshot-001",
      fleet_id: "recorded-fleet",
      as_of: "2026-09-15T23:05:20Z",
      symbol_count: rows.length,
      symbols: rows.map(({ symbol, price }) => ({ symbol, price, return_pct: null })),
    },
  });
  bundle.artifactIndex = new Map(bundle.artifactIndex).set(fleetReference.name, fleetReference);
  bundle.navigatorFleetVariants = rows.map(({ symbol, name, price, ma, pct }) => ({
    market: {
      ...original,
      symbol,
      name,
      category: "equity",
      points: original.points.map((point, index) => ({
        ...point, o: price - 2, h: price + 1, l: price - 3,
        c: index === original.points.length - 1 ? price : price - 1, ma,
      })),
      summary: { ...original.summary, last_price: price, last_ma: ma, pct_vs_ma: pct },
    },
    capturedAt,
    sourceIdentity: "navigator-local-api",
    navigatorGitRevision: "b".repeat(40),
    navigatorSourceSha256: "c".repeat(64),
    navigatorWorktreeDirty: true,
    reference: {
      ...artifact("navigator_fleet_market", `presentation/navigator_fleet/${symbol}-1d-ma250.json`, "navigator.api.ohlc.v1"),
      producer: "navigator",
      observed_at: capturedAt,
    },
  }));
  bundle.baseUrl = `/live/revisions/${"a".repeat(64)}/`;
  return bundle;
}

function liveMissionWithTapeCaptures() {
  const bundle = liveMissionWithFleetCaptures();
  const spy = bundle.navigatorFleetVariants!.find(({ market }) => market.symbol === "SPY")!;
  bundle.navigatorFleetVariants = [...bundle.navigatorFleetVariants!, ...([250, 20] as const).map((period) => ({
    ...spy,
    capturedAt: "2026-09-16T15:30:00Z",
    sourceIdentity: `navigator-spy-hourly-ma${period}`,
    market: {
      ...spy.market, timeframe: "1h" as const, ma_period: period,
      points: spy.market.points.map((point, index) => ({ ...point, c: index === 1 ? 557.21 : 556.21, h: 558, o: 556, l: 555, ma: 552 })),
      summary: { ...spy.market.summary, ma_period: period, last_price: 557.21, last_ma: 552, pct_vs_ma: 0.94 },
    },
    reference: { ...spy.reference, path: `presentation/navigator_fleet/SPY-1h-ma${period}.json`, observed_at: "2026-09-16T15:30:00Z" },
  }))];
  const snapshot = bundle.evidence.get("oracle_normalized_snapshot")!.document!;
  snapshot.symbols = [...Array.isArray(snapshot.symbols) ? snapshot.symbols : [], { symbol: "XLF", price: 52.25, return_pct: null }];
  snapshot.symbol_count = 3;
  return bundle;
}

function supplyLiveMission(bundle: ReturnType<typeof liveMission>) {
  window.history.replaceState(null, "", "/");
  vi.mocked(loadLiveMissionFeed).mockResolvedValue({
    schema_version: "blackpod.cabin_feed.v1", status: "READY",
    checked_at: "2026-09-16T15:31:00Z", observed_at: bundle.snapshot.observed_at,
    message: "Verified mission", mission_id: bundle.summary.mission_id,
    publication_id: "a".repeat(64), base_url: `revisions/${"a".repeat(64)}/`,
  });
  vi.mocked(loadLiveMissionBundle).mockResolvedValue(bundle);
}

describe("Captain's Cabin", () => {
  beforeEach(() => {
    window.localStorage.removeItem(LOCAL_WATCHLIST_KEY);
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

  it("opens a publication-bound live price subscription only while the full Navigator is expanded", async () => {
    const bundle = liveMission();
    bundle.baseUrl = `/live/revisions/${"a".repeat(64)}/`;
    supplyLiveMission(bundle);
    const streams: { url: string; close: ReturnType<typeof vi.fn> }[] = [];
    vi.stubGlobal("EventSource", class {
      close = vi.fn();
      onmessage = null;
      onerror = null;
      constructor(readonly url: string) { streams.push(this); }
    });
    const visible = vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    try {
      render(<App />);
      const opener = await screen.findByRole("button", { name: "Open Navigator ship view for AAPL" });
      expect(streams).toHaveLength(0);
      fireEvent.click(opener);
      expect(screen.getByLabelText("Live Navigator market data")).toBeInTheDocument();
      expect(streams).toHaveLength(1);
      expect(streams[0].url).toBe(`/live/navigator/price/${"a".repeat(64)}/AAPL`);
      fireEvent.keyDown(window, { key: "Escape" });
      expect(streams[0].close).toHaveBeenCalledTimes(1);
      expect(screen.queryByLabelText("Live Navigator market data")).not.toBeInTheDocument();
      await waitFor(() => expect(opener).toHaveFocus());
    } finally {
      visible.mockRestore();
      vi.unstubAllGlobals();
    }
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
    { trigger: "Focus Captain's Log", dialog: "Captain’s Log", close: "Return to bridge" },
    { trigger: "Open Shadow Plan details", dialog: "Navigator SHADOW plan", close: "Return to bridge" },
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

  it.each<[string, CabinPanelId]>([
    ["Open market context", "market"], ["Open fleet status", "fleet"],
    ["Open ModelDock provenance", "modeldock"], ["Open timeframe details", "timeframe"],
    ["Open mission details", "mission"], ["Open market timing", "market-timing"],
    ["Open mission time", "mission-time"], ["Open approval scope", "approval"],
    ["Open watchlist and warnings", "watchlist"], ["Open risk and governance", "governance"],
    ["Open Governor disposition", "governor"], ["Open portfolio exposure", "portfolio"],
    ["Open model routing", "model-routing"], ["Open safety boundary", "safety"],
  ])("opens %s without changing or reloading the mission", async (name, panel) => {
    const bundle = missionWithNavigatorMarket();
    const before = JSON.stringify(bundle);
    mockedLoadMissionBundle.mockResolvedValue(bundle);
    render(<App />);
    const opener = (await screen.findAllByRole("button", { name }))[0];
    fireEvent.click(opener);
    const dialog = screen.getByRole("dialog", { name: CABIN_PANEL_TITLES[panel] });
    expect(opener).toHaveAttribute("aria-expanded", "true");
    expect(opener.closest("[inert]")).not.toBeNull();
    expect(within(dialog).getByRole("button", { name: "Return to bridge" })).toHaveFocus();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(opener).toHaveFocus());
    expect(opener).toHaveAttribute("aria-expanded", "false");
    expect(mockedLoadMissionBundle).toHaveBeenCalledOnce();
    expect(JSON.stringify(bundle)).toBe(before);
  });

  it("opens the recorded fleet from Admiral and returns focus after viewing", async () => {
    render(<App />);
    const opener = await screen.findByRole("button", { name: "Admiral Recorded fleet" });
    fireEvent.click(opener);
    const dialog = screen.getByRole("dialog", { name: CABIN_PANEL_TITLES.fleet });
    expect(within(dialog).getByRole("region", { name: "Recorded fleet overview" })).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Return to bridge" }));
    expect(opener).toHaveFocus();
  });

  it.each(["Open fleet status", "Admiral Recorded fleet"])("reviews captured fleet symbols from %s without changing the mission or reloading data", async (name) => {
    window.history.replaceState(null, "", "/");
    const bundle = liveMissionWithFleetCaptures();
    const serialize = () => JSON.stringify(bundle, (_key, value: unknown) => value instanceof Map ? [...value] : value);
    const before = serialize();
    const originalMarket = bundle.navigatorMarket;
    const originalSummary = bundle.summary;
    const originalSnapshot = bundle.snapshot;
    vi.mocked(loadLiveMissionFeed).mockResolvedValue({
      schema_version: "blackpod.cabin_feed.v1", status: "READY",
      checked_at: "2026-09-16T14:01:00Z", observed_at: bundle.snapshot.observed_at,
      message: "Verified mission", mission_id: bundle.summary.mission_id,
      publication_id: "a".repeat(64), base_url: `revisions/${"a".repeat(64)}/`,
    });
    vi.mocked(loadLiveMissionBundle).mockResolvedValue(bundle);
    // Every capture is already in the verified bundle. Selection must not call
    // a market provider, ModelDock, or any other fetch-based endpoint.
    const network = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("Unexpected network request during chart review"));
    try {
      render(<App />);
      const opener = await screen.findByRole("button", { name });
      const overview = screen.getByRole("figure", { name: "Navigator ship view for AAPL" });
      const originalOverview = overview.innerHTML;
      expect(screen.getByText("APPROVED · COMPLETE")).toBeInTheDocument();
      fireEvent.click(opener);
      const fleet = screen.getByRole("dialog", { name: CABIN_PANEL_TITLES.fleet });
      const review = within(fleet).getByRole("button", { name: "Review XLK in Navigator" });
      review.focus();
      fireEvent.click(review);

      const navigator = screen.getByRole("dialog", { name: "Navigator Ship View" });
      expect(screen.queryByRole("dialog", { name: CABIN_PANEL_TITLES.fleet })).not.toBeInTheDocument();
      const symbolPicker = within(navigator).getByRole("combobox", { name: "Navigator review symbol" });
      expect(symbolPicker).toHaveValue("XLK");
      expect(within(navigator).getByRole("combobox", { name: "Captured bar interval" })).toHaveValue("1d");
      expect(within(navigator).getByRole("combobox", { name: "Captured moving average" })).toHaveValue("250");
      const xlk = within(navigator).getByRole("figure", { name: "Navigator ship view for XLK" });
      expect(within(xlk).getByText("$183.74")).toBeInTheDocument();
      expect(within(xlk).getByText("$180.00")).toBeInTheDocument();
      expect(within(xlk).getByTestId("current-price-ship")).toHaveAttribute("aria-label", "Ship at latest close $183.74");
      expect(within(navigator).getByText(/XLK · 1d · MA250 · captured 2026-09-16T14:00:00Z/)).toBeInTheDocument();

      fireEvent.change(symbolPicker, { target: { value: "SPY" } });
      expect(symbolPicker).toHaveValue("SPY");
      expect(within(navigator).getByRole("combobox", { name: "Captured bar interval" })).toHaveValue("1d");
      expect(within(navigator).getByRole("combobox", { name: "Captured moving average" })).toHaveValue("250");
      const spy = within(navigator).getByRole("figure", { name: "Navigator ship view for SPY" });
      expect(within(spy).getByText("$550.25")).toBeInTheDocument();
      expect(within(spy).getByText("$520.00")).toBeInTheDocument();
      expect(within(spy).getByTestId("current-price-ship")).toHaveAttribute("aria-label", "Ship at latest close $550.25");
      expect(within(navigator).queryByRole("figure", { name: "Navigator ship view for XLK" })).not.toBeInTheDocument();
      expect(within(navigator).queryByText("$183.74")).not.toBeInTheDocument();
      expect(within(navigator).getByText(/SPY · 1d · MA250 · captured 2026-09-16T14:00:00Z/)).toBeInTheDocument();
      expect(overview.innerHTML).toBe(originalOverview);
      expect(serialize()).toBe(before);

      fireEvent.keyDown(window, { key: "Escape" });
      await waitFor(() => expect(opener).toHaveFocus());
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(screen.getByRole("figure", { name: "Navigator ship view for AAPL" })).toBe(overview);
      expect(screen.getByText("APPROVED · COMPLETE")).toBeInTheDocument();
      expect(screen.getByText("APPROVED_FOR_HANDOFF")).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Open Navigator reference tape" }));
      const tape = screen.getByRole("dialog", { name: "Navigator reference tape" });
      expect(within(tape).getByText("AAPL · Apple Inc.")).toBeInTheDocument();
      expect(within(tape).getByText("$215.00")).toBeInTheDocument();
      expect(within(tape).getByText("$202.20")).toBeInTheDocument();
      expect(within(tape).getByRole("combobox", { name: "Reference tape symbol" })).toHaveValue("AAPL");
      expect(within(tape).queryByText("$550.25")).not.toBeInTheDocument();
      expect(bundle.navigatorMarket).toBe(originalMarket);
      expect(bundle.summary).toBe(originalSummary);
      expect(bundle.snapshot).toBe(originalSnapshot);
      expect(bundle.summary.symbol).toBe("AAPL");
      expect(serialize()).toBe(before);
      expect(loadLiveMissionFeed).toHaveBeenCalledOnce();
      expect(loadLiveMissionBundle).toHaveBeenCalledOnce();
      expect(mockedLoadMissionBundle).not.toHaveBeenCalled();
      expect(network).not.toHaveBeenCalled();
    } finally {
      network.mockRestore();
    }
  });

  it.each(["Open fleet status", "Admiral Recorded fleet", "Open watchlist and warnings"])("opens details from %s and hands the exact selected capture to Navigator while retaining Cabin focus", async (name) => {
    const bundle = liveMissionWithTapeCaptures();
    supplyLiveMission(bundle);
    const serialize = () => JSON.stringify(bundle, (_key, value: unknown) => value instanceof Map ? [...value] : value);
    const before = serialize();
    const savedWatchlist = JSON.stringify({ version: 1, symbols: ["MSFT"] });
    window.localStorage.setItem(LOCAL_WATCHLIST_KEY, savedWatchlist);
    const network = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("Unexpected fetch during captured reference review"));
    const storageWrite = vi.spyOn(Storage.prototype, "setItem");
    try {
      render(<App />);
      const opener = await screen.findByRole("button", { name });
      const overview = screen.getByRole("figure", { name: "Navigator ship view for AAPL" });
      const originalOverview = overview.innerHTML;
      fireEvent.click(opener);
      const details = screen.getByRole("button", { name: "View XLK reference tape" });
      details.focus();
      expect(screen.getByRole("button", { name: "Review XLK in Navigator" })).toBeEnabled();
      fireEvent.click(details);
      const tape = screen.getByRole("dialog", { name: "Navigator reference tape" });
      expect(within(tape).getByRole("button", { name: "Return to bridge" })).toHaveFocus();
      expect(within(tape).getByRole("combobox", { name: "Reference tape symbol" })).toHaveValue("XLK");
      expect(within(tape).getByText("$183.74")).toBeInTheDocument();
      expect(within(tape).getByRole("button", { name: "Open full Navigator" })).toBeEnabled();
      fireEvent.change(within(tape).getByRole("combobox", { name: "Reference tape symbol" }), { target: { value: "SPY" } });
      fireEvent.change(within(tape).getByRole("combobox", { name: "Reference tape bar interval" }), { target: { value: "1h" } });
      fireEvent.change(within(tape).getByRole("combobox", { name: "Reference tape moving average" }), { target: { value: "20" } });
      expect(within(tape).getByRole("combobox", { name: "Reference tape moving average" })).toHaveValue("20");
      expect(within(tape).getByText("$557.21")).toBeInTheDocument();
      fireEvent.click(within(tape).getByRole("button", { name: "Open full Navigator" }));

      const navigator = screen.getByRole("dialog", { name: "Navigator Ship View" });
      expect(screen.queryByRole("dialog", { name: "Navigator reference tape" })).not.toBeInTheDocument();
      expect(within(navigator).getByRole("combobox", { name: "Navigator review symbol" })).toHaveValue("SPY");
      expect(within(navigator).getByRole("combobox", { name: "Captured bar interval" })).toHaveValue("1h");
      expect(within(navigator).getByRole("combobox", { name: "Captured moving average" })).toHaveValue("20");
      const selected = within(navigator).getByRole("figure", { name: "Navigator ship view for SPY" });
      expect(within(selected).getByTestId("current-price-ship")).toHaveAttribute("aria-label", "Ship at latest close $557.21");
      expect(within(navigator).getByText(/SPY · 1h · MA20 · captured 2026-09-16T15:30:00Z · navigator-spy-hourly-ma20/)).toBeInTheDocument();
      expect(overview.innerHTML).toBe(originalOverview);
      fireEvent.keyDown(window, { key: "Escape" });
      await waitFor(() => expect(opener).toHaveFocus());

      // The desk paper always starts from the original mission reference.
      fireEvent.click(screen.getByRole("button", { name: "Open Navigator reference tape" }));
      const originalTape = screen.getByRole("dialog", { name: "Navigator reference tape" });
      expect(within(originalTape).getByRole("combobox", { name: "Reference tape symbol" })).toHaveValue("AAPL");
      expect(within(originalTape).getByRole("combobox", { name: "Reference tape bar interval" })).toHaveValue("1d");
      expect(within(originalTape).getByRole("combobox", { name: "Reference tape moving average" })).toHaveValue("250");
      expect(within(originalTape).getByText("$215.00")).toBeInTheDocument();
      expect(serialize()).toBe(before);
      expect(window.localStorage.getItem(LOCAL_WATCHLIST_KEY)).toBe(savedWatchlist);
      expect(storageWrite).not.toHaveBeenCalled();
      expect(network).not.toHaveBeenCalled();
      expect(loadLiveMissionFeed).toHaveBeenCalledOnce();
      expect(loadLiveMissionBundle).toHaveBeenCalledOnce();
    } finally {
      network.mockRestore();
      storageWrite.mockRestore();
    }
  });

  it.each(["Open fleet status", "Admiral Recorded fleet", "Open watchlist and warnings"])("keeps uncaptured row details available from %s without substituting a chart", async (name) => {
    const bundle = liveMissionWithTapeCaptures();
    supplyLiveMission(bundle);
    render(<App />);
    const opener = await screen.findByRole("button", { name });
    fireEvent.click(opener);
    const row = screen.getByRole("rowheader", { name: "XLF" }).closest("tr")!;
    expect(within(row).queryByRole("button", { name: "Review XLF in Navigator" })).not.toBeInTheDocument();
    expect(within(row).getByText("No chart capture")).toBeInTheDocument();
    const details = within(row).getByRole("button", { name: "View XLF reference tape" });
    details.focus();
    fireEvent.click(details);
    const tape = screen.getByRole("dialog", { name: "Navigator reference tape" });
    expect(within(tape).getByRole("button", { name: "Return to bridge" })).toHaveFocus();
    expect(within(tape).getByRole("combobox", { name: "Reference tape symbol" })).toHaveValue("XLF");
    expect(within(tape).getByText("XLF · recorded item details")).toBeInTheDocument();
    expect(within(tape).getByText("52.25")).toBeInTheDocument();
    expect(within(tape).queryByRole("button", { name: "Open full Navigator" })).not.toBeInTheDocument();
    expect(within(tape).queryByRole("combobox", { name: "Reference tape bar interval" })).not.toBeInTheDocument();
    expect(within(tape).queryByText("$215.00")).not.toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(opener).toHaveFocus());
    expect(loadLiveMissionBundle).toHaveBeenCalledOnce();
  });

  it("opens the full Navigator ledger from Shadow Plan and restores the paper trigger", async () => {
    render(<App />);
    const opener = await screen.findByRole("button", { name: "Open Shadow Plan details" });
    fireEvent.click(opener);
    fireEvent.click(screen.getByRole("button", { name: "Read full Navigator ledger" }));
    expect(screen.getByRole("dialog", { name: "Navigator" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Navigator SHADOW plan" })).not.toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(opener).toHaveFocus());
  });

  it.each(["Open fleet status", "Admiral Recorded fleet"])("moves from %s to local watchlist and returns to the original trigger", async (name) => {
    const bundle = missionWithNavigatorMarket();
    const before = JSON.stringify(bundle);
    mockedLoadMissionBundle.mockResolvedValue(bundle);
    render(<App />);
    const opener = await screen.findByRole("button", { name });
    fireEvent.click(opener);
    const manage = screen.getByRole("button", { name: "Manage local watchlist" });
    manage.focus();
    fireEvent.click(manage);
    const dialog = screen.getByRole("dialog", { name: CABIN_PANEL_TITLES.watchlist });
    expect(within(dialog).getByText("Local preferences · mission evidence remains read-only")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Return to bridge" })).toHaveFocus();
    const editor = within(dialog).getByRole("region", { name: "Local watchlist" });
    fireEvent.change(within(editor).getByRole("textbox", { name: "Symbol" }), { target: { value: " msft " } });
    fireEvent.submit(within(editor).getByRole("form", { name: "Add to local watchlist" }));
    expect(within(editor).getByText("MSFT")).toBeInTheDocument();
    expect(JSON.parse(window.localStorage.getItem(LOCAL_WATCHLIST_KEY)!)).toEqual({ version: 1, symbols: ["MSFT"] });
    expect(JSON.stringify(bundle)).toBe(before);
    expect(mockedLoadMissionBundle).toHaveBeenCalledOnce();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(opener).toHaveFocus());
    fireEvent.click(screen.getByRole("button", { name: "Open watchlist and warnings" }));
    expect(screen.getByRole("button", { name: "Remove MSFT from local watchlist" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove MSFT from local watchlist" }));
    expect(screen.getByRole("textbox", { name: "Symbol" })).toHaveFocus();
    expect(JSON.parse(window.localStorage.getItem(LOCAL_WATCHLIST_KEY)!)).toEqual({ version: 1, symbols: [] });
    expect(JSON.stringify(bundle)).toBe(before);
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
