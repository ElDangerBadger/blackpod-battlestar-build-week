import { useEffect, useMemo, useRef, useState } from "react";

import { BookFocus } from "./books/BookFocus";
import { buildBookDefinitions, type BookDefinition, type StageBookId } from "./books/bookPages";
import { BottomNavigation, type CabinDestination } from "./components/BottomNavigation";
import { CaptainsLog } from "./components/CaptainsLog";
import { MarketConditions, MissionChart, SentryAlerts, ShadowPlanPaper } from "./components/DeskPanels";
import { Notice } from "./components/Notice";
import {
  NavigatorShipView,
  type NavigatorShipData,
  type NavigatorShipDisplayContext,
} from "./components/NavigatorShipView";
import { ReplayControls } from "./components/ReplayControls";
import { StatusPanel } from "./components/StatusPanel";
import { SystemsPanel } from "./components/SystemsPanel";
import { loadMissionBundle, MissionBundleLoadError, type MissionBundle } from "./data/loadMission";
import { createMissionViewModel, type MissionViewModel } from "./data/viewModel";
import { useReplayTheater } from "./replay/useReplayTheater";
import { CabinScene } from "./scene/CabinScene";

export type PresentationMode = "DEMO" | "LIVE";

const PRESENTATION_BASE_URLS: Record<PresentationMode, string> = {
  DEMO: `${import.meta.env.BASE_URL}demo/approved/`,
  LIVE: `${import.meta.env.BASE_URL}demo/live/`,
};

type NoticeState = "sentry" | "admiral" | "config" | "logbook" | null;

export default function App() {
  const [presentationMode, setPresentationMode] = useState<PresentationMode>(() => modeFromSearch(window.location.search));
  const [mission, setMission] = useState<MissionViewModel | null>(null);
  const [loadError, setLoadError] = useState<{ message: string; fallbackMarkdown: string | null } | null>(null);

  useEffect(() => {
    let active = true;
    setMission(null);
    setLoadError(null);
    const baseUrl = PRESENTATION_BASE_URLS[presentationMode];
    loadMissionBundle(baseUrl)
      .then((bundle) => {
        assertPresentationMode(bundle, presentationMode);
        if (active) setMission(createMissionViewModel(bundle));
      })
      .catch((error: unknown) => {
        if (!active) return;
        const message = error instanceof Error ? error.message : "The canonical mission pack could not be loaded.";
        setLoadError({
          message,
          fallbackMarkdown: error instanceof MissionBundleLoadError ? error.fallbackMarkdown : null,
        });
    });
    return () => { active = false; };
  }, [presentationMode]);

  const chooseMode = (mode: PresentationMode) => {
    if (mode === presentationMode) return;
    const url = new URL(window.location.href);
    url.searchParams.set("mode", mode.toLowerCase());
    window.history.replaceState(null, "", url);
    setPresentationMode(mode);
  };

  if (loadError) return <LoadFailure mode={presentationMode} message={loadError.message} fallbackMarkdown={loadError.fallbackMarkdown} onSelectMode={chooseMode} />;
  if (!mission) return <LoadingCabin mode={presentationMode} />;
  return <MissionCabin mission={mission} presentationMode={presentationMode} onSelectMode={chooseMode} />;
}

function MissionCabin({
  mission,
  presentationMode,
  onSelectMode,
}: {
  mission: MissionViewModel;
  presentationMode: PresentationMode;
  onSelectMode: (mode: PresentationMode) => void;
}) {
  const books = useMemo(() => buildBookDefinitions(mission), [mission]);
  const [selectedBookId, setSelectedBookId] = useState<StageBookId | null>(null);
  const [notice, setNotice] = useState<NoticeState>(null);
  const [activeDestination, setActiveDestination] = useState<CabinDestination>("bridge");
  const [shipFocused, setShipFocused] = useState(false);
  const shipTriggerRef = useRef<HTMLButtonElement>(null);
  const theater = useReplayTheater();
  const currentEntry = theater.revealCount > 0 ? mission.captainsLog[theater.revealCount - 1] : undefined;

  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setSelectedBookId(null);
      setNotice(null);
      if (shipFocused) queueMicrotask(() => shipTriggerRef.current?.focus());
      setShipFocused(false);
      setActiveDestination("bridge");
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [shipFocused]);

  const selectedBook = selectedBookId === null ? undefined : books.find((book) => book.id === selectedBookId);
  const shipData = useMemo<NavigatorShipData | null>(() => {
    if (!mission.market.navigatorMarket) return null;
    return mission.market.navigatorMarket;
  }, [mission.market.navigatorMarket]);
  const shipContext = useMemo<NavigatorShipDisplayContext>(() => ({
    presentationMode,
    runMode: mission.status.runMode,
    capturedAt: mission.market.capturedAt,
    latestCompletedBar: mission.market.latestCompletedBar,
    marketStatus: mission.market.marketStatus,
    exposure: mission.portfolio.activeExposure,
  }), [mission, presentationMode]);
  const activeMilestoneBook = milestoneBookId(theater.currentStage);
  const announcement = currentEntry
    ? `${currentEntry.stage}: ${currentEntry.status}. ${currentEntry.summary}`
    : "Mission replay reset. No stage has been revealed.";

  const selectBook = (id: StageBookId) => {
    setNotice(null);
    setShipFocused(false);
    setSelectedBookId(id);
    setActiveDestination(destinationForBook(id));
  };

  const closeFocus = () => {
    setSelectedBookId(null);
    setNotice(null);
    setShipFocused(false);
    setActiveDestination("bridge");
  };

  const closeShip = () => {
    setShipFocused(false);
    queueMicrotask(() => shipTriggerRef.current?.focus());
  };

  const navigate = (destination: CabinDestination) => {
    setActiveDestination(destination);
    setSelectedBookId(null);
    setNotice(null);
    setShipFocused(false);
    if (destination === "navigator" || destination === "oracle" || destination === "council") {
      setSelectedBookId(destination);
    } else if (destination !== "bridge") {
      setNotice(destination);
    }
  };

  const governorRevealed = theater.revealed.has("GOVERNOR");
  const operatorRevealed = theater.revealed.has("OPERATOR");
  const modeldockRevealed = theater.revealed.has("MODELDOCK");
  const navigatorRevealed = theater.revealed.has("NAVIGATOR");
  const missionRevealed = theater.revealed.has("MISSION");

  return (
    <main data-replay-stage={theater.currentStage ?? "RESET"}>
      <CabinScene
        missionBriefHref={`${PRESENTATION_BASE_URLS[presentationMode]}presentation/mission_brief.html`}
        status={<StatusPanel
          presentationMode={presentationMode}
          symbol={mission.status.symbol}
          companyName={mission.market.companyName}
          timeframe={mission.market.timeframe}
          marketStatus={mission.market.marketStatus}
          latestCompletedBar={mission.market.latestCompletedBar}
          mode={mission.status.runMode}
          outcome={mission.status.outcome}
          phase={mission.status.currentPhase}
          missionId={mission.status.missionId}
          timestamp={mission.status.startedAt}
          approvalScope={mission.status.approvalScope}
          snapshotCount={mission.status.snapshotCount}
          modeldockMode={modeldockRevealed ? mission.modeldock.mode : "AWAITING REVEAL"}
          modeldockStatus={modeldockRevealed ? mission.modeldock.status : "PENDING"}
          activeMilestone={currentEntry?.stage ?? null}
          activeStatus={currentEntry?.status ?? null}
        />}
        books={books.map((book) => ({
          id: book.id,
          label: book.title,
          selected: selectedBookId === book.id || activeMilestoneBook === book.id,
          revealed: bookIsRevealed(book.id, theater.revealed),
          onSelect: selectBook,
          children: <DeskBookSummary book={book} />,
        }))}
        sentryAlerts={<SentryAlerts
          warnings={theater.revealed.has("ORACLE") ? mission.warnings : []}
          onFocus={() => navigate("sentry")}
        />}
        marketConditions={<MarketConditions symbol={mission.status.symbol} market={mission.market} />}
        captainsLog={<CaptainsLog
          entries={mission.captainsLog}
          revealedStages={theater.revealed}
          onFocus={() => navigate("logbook")}
        />}
        missionChart={<MissionChart
          missionId={mission.status.missionId}
          snapshotCount={mission.status.snapshotCount}
          revision={mission.status.snapshotCount}
          shipData={shipData}
          shipContext={shipContext}
          triggerRef={shipTriggerRef}
          onOpenShip={() => setShipFocused(true)}
        />}
        paperOrder={navigatorRevealed
          && mission.status.navigatorMode === "SHADOW"
          && mission.status.navigatorPlanStatus === "CREATED"
          ? <ShadowPlanPaper
              allowed={mission.safety.allowedOperations}
              prohibited={mission.safety.prohibitedOperations}
              outcome={missionRevealed ? mission.status.outcome : "AWAITING MISSION REVEAL"}
            />
          : <AwaitingShadowPlan navigatorRevealed={navigatorRevealed} />}
        systemsPanel={<SystemsPanel
          presentationMode={presentationMode}
          warnings={theater.revealed.has("ORACLE") ? mission.warnings : []}
          governorDisposition={governorRevealed ? mission.status.governorDisposition ?? "Not present" : "Awaiting reveal"}
          operatorResult={operatorRevealed ? mission.status.operatorResult : "Awaiting reveal"}
          approvalScope={missionRevealed ? mission.status.approvalScope : "Awaiting mission reveal"}
          modeldockMode={modeldockRevealed ? mission.modeldock.mode : "Awaiting reveal"}
          provider={modeldockRevealed ? mission.modeldock.provider : null}
          model={modeldockRevealed ? mission.modeldock.model : null}
          traceId={modeldockRevealed ? mission.modeldock.traceId : null}
          latencyMs={modeldockRevealed ? mission.modeldock.latencyMs : null}
          lastSuccessfulInference={modeldockRevealed ? mission.modeldock.lastSuccessfulInference : null}
          modeldockAvailability={modeldockRevealed ? mission.modeldock.availability : "Awaiting reveal"}
          mocked={modeldockRevealed ? mission.modeldock.mocked : null}
          portfolio={mission.portfolio}
          allowedOperations={mission.safety.allowedOperations}
          prohibitedOperations={mission.safety.prohibitedOperations}
        />}
        navigation={<BottomNavigation active={activeDestination} onNavigate={navigate} />}
        foreground={<>
          <PresentationModeControl mode={presentationMode} runMode={mission.status.runMode} onSelect={onSelectMode} />
          <ReplayControls theater={theater} announcement={announcement} />
          {selectedBook ? <BookFocus book={selectedBook} artifactBaseUrl={mission.baseUrl} onClose={closeFocus} /> : null}
          {notice ? <CabinNotice notice={notice} mission={mission} onClose={closeFocus} /> : null}
          {shipFocused && shipData ? <NavigatorShipFocus data={shipData} context={shipContext} onClose={closeShip} /> : null}
        </>}
      />
    </main>
  );
}

function PresentationModeControl({
  mode,
  runMode,
  onSelect,
}: {
  mode: PresentationMode;
  runMode: string;
  onSelect: (mode: PresentationMode) => void;
}) {
  return (
    <aside className="presentation-mode-control" aria-label="Presentation data mode">
      <strong>{mode}</strong>
      <span>{mode === "DEMO" ? `${runMode} frozen mission` : `${runMode} current mission`}</span>
      <div role="group" aria-label="Select presentation mode">
        <button type="button" aria-pressed={mode === "DEMO"} onClick={() => onSelect("DEMO")}>Demo</button>
        <button type="button" aria-pressed={mode === "LIVE"} onClick={() => onSelect("LIVE")}>Live</button>
      </div>
    </aside>
  );
}

function NavigatorShipFocus({
  data,
  context,
  onClose,
}: {
  data: NavigatorShipData;
  context: NavigatorShipDisplayContext;
  onClose: () => void;
}) {
  return (
    <div className="navigator-focus-layer" role="dialog" aria-modal="true" aria-labelledby="navigator-focus-title">
      <button className="book-focus-scrim" type="button" aria-label="Close Navigator ship view" onClick={onClose} />
      <section className="navigator-focus-surface">
        <header>
          <div>
            <p className="eyebrow">Supplemental read-only Navigator market reference</p>
            <h2 id="navigator-focus-title">Navigator Ship View</h2>
          </div>
          <button type="button" onClick={onClose} autoFocus>Return to bridge</button>
        </header>
        <NavigatorShipView data={data} context={context} variant="interactive" />
        <p className="focus-safety-line">Not Oracle evidence · SHADOW presentation only · no trade or order execution</p>
      </section>
    </div>
  );
}

function DeskBookSummary({ book }: { book: BookDefinition }) {
  return (
    <div className="desk-book-summary">
      <strong>{book.state}</strong>
      {book.deskLines.slice(0, 3).map((line) => <p key={line}>{line}</p>)}
      <span>Open book · {book.pages.length} pages</span>
    </div>
  );
}

function CabinNotice({ notice, mission, onClose }: { notice: Exclude<NoticeState, null>; mission: MissionViewModel; onClose: () => void }) {
  if (notice === "logbook") {
    return (
      <Notice title="Captain’s Log" onClose={onClose}>
        <div className="focused-log">
          <CaptainsLog entries={mission.captainsLog} revealedStages={new Set(mission.captainsLog.map((entry) => entry.stage))} />
        </div>
      </Notice>
    );
  }
  if (notice === "sentry") {
    return (
      <Notice title="Mission warnings" onClose={onClose}>
        {mission.warnings.length ? <ul>{mission.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul> : <p>No warnings are recorded.</p>}
        <p>These warnings are copied from canonical mission evidence without reinterpretation.</p>
      </Notice>
    );
  }
  return (
    <Notice title={notice === "admiral" ? "Admiral" : "Configuration"} onClose={onClose}>
      <p>Not included in this Build Week presentation.</p>
      <p>The Captain’s Cabin does not expose settings, approval actions, trading controls, or backend mutation.</p>
    </Notice>
  );
}

function AwaitingShadowPlan({ navigatorRevealed = false }: { navigatorRevealed?: boolean }) {
  return (
    <section className="paper-order-copy" aria-label="Navigator SHADOW plan pending reveal">
      <span className="paper-title">Shadow plan</span>
      <strong>NO ORDER EXECUTION</strong>
      <p>{navigatorRevealed
        ? "No canonical Navigator SHADOW plan was created."
        : "Awaiting canonical Navigator evidence in mission replay."}</p>
    </section>
  );
}

function milestoneBookId(stage: string | null): StageBookId | null {
  switch (stage) {
    case "HARBORMASTER": return "harbormaster";
    case "ORACLE":
    case "MODELDOCK": return "oracle";
    case "COUNCIL": return "council";
    case "GOVERNOR": return "governor";
    case "OPERATOR":
    case "NAVIGATOR": return "navigator";
    default: return null;
  }
}

function destinationForBook(id: StageBookId): CabinDestination {
  if (id === "oracle" || id === "council" || id === "navigator") return id;
  return "bridge";
}

function bookIsRevealed(id: StageBookId, revealed: ReadonlySet<string>): boolean {
  if (id === "harbormaster") return revealed.has("HARBORMASTER");
  if (id === "oracle") return revealed.has("ORACLE");
  if (id === "council") return revealed.has("COUNCIL");
  if (id === "governor") return revealed.has("GOVERNOR");
  return revealed.has("NAVIGATOR");
}

function LoadingCabin({ mode }: { mode: PresentationMode }) {
  return (
    <main className="cabin-loading" aria-live="polite">
      <p className="eyebrow">BlackPod Battlestar</p>
      <h1>Opening the Captain’s Cabin in {mode} mode…</h1>
      <p>Validating canonical mission artifacts and evidence hashes.</p>
    </main>
  );
}

function LoadFailure({
  mode,
  message,
  fallbackMarkdown,
  onSelectMode,
}: {
  mode: PresentationMode;
  message: string;
  fallbackMarkdown: string | null;
  onSelectMode: (mode: PresentationMode) => void;
}) {
  return (
    <main className="cabin-loading cabin-load-failure" role="alert">
      <p className="eyebrow">Captain’s Cabin unavailable</p>
      <h1>Mission evidence could not be validated.</h1>
      <p>{mode} mission pack: {message}</p>
      <p>No alternate mode was substituted. Prepare the requested pack, then reload this read-only presentation.</p>
      <div className="load-mode-actions" aria-label="Select presentation mode">
        <button type="button" aria-pressed={mode === "DEMO"} onClick={() => onSelectMode("DEMO")}>Demo</button>
        <button type="button" aria-pressed={mode === "LIVE"} onClick={() => onSelectMode("LIVE")}>Live</button>
      </div>
      {fallbackMarkdown ? (
        <details className="captains-log-fallback">
          <summary>Read Captain’s Log Markdown fallback</summary>
          <pre>{fallbackMarkdown}</pre>
        </details>
      ) : null}
    </main>
  );
}

function modeFromSearch(search: string): PresentationMode {
  return new URLSearchParams(search).get("mode")?.toLowerCase() === "live" ? "LIVE" : "DEMO";
}

function assertPresentationMode(bundle: MissionBundle, mode: PresentationMode): void {
  if (mode !== "LIVE") return;
  const call = bundle.snapshot.stages.oracle.modeldock_calls.at(-1);
  if (bundle.summary.run_mode !== "LIVE" || bundle.manifest.run_mode !== "LIVE") {
    throw new Error("LIVE mode requires a canonical LIVE mission pack");
  }
  if (
    bundle.manifest.modeldock_mode !== "LIVE"
    || call?.status !== "SUCCEEDED"
    || call.run_mode !== "LIVE"
    || call.provider !== "mlx"
    || call.mocked !== false
  ) {
    throw new Error("LIVE mode requires a successful non-mocked local MLX inference record");
  }
}
