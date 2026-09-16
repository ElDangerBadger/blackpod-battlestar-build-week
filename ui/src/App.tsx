import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";

import { BookFocus } from "./books/BookFocus";
import { buildBookDefinitions, type BookDefinition, type StageBookId } from "./books/bookPages";
import { BottomNavigation, type CabinDestination } from "./components/BottomNavigation";
import { CaptainsLog } from "./components/CaptainsLog";
import { MarketConditions, MissionChart, SentryAlerts, ShadowPlanPaper } from "./components/DeskPanels";
import { Notice } from "./components/Notice";
import { MissionWarnings } from "./components/MissionWarnings";
import { NavigatorReferenceTape } from "./components/NavigatorReferenceTape";
import { NavigatorOceanBoundary } from "./components/NavigatorOceanBoundary";
import { useReducedMotion } from "./components/navigator-ocean/useReducedMotion";
import { ReplayControls } from "./components/ReplayControls";
import { StatusPanel } from "./components/StatusPanel";
import { SystemsPanel } from "./components/SystemsPanel";
import type { NavigatorMarket } from "./contracts/cabinContext";
import type { NavigatorMarketVariant } from "./contracts/navigatorCatalog";
import { loadMissionBundle, MissionBundleLoadError } from "./data/loadMission";
import { evidenceFreshness, useLiveMission, type LiveMissionState } from "./data/useLiveMission";
import { createMissionViewModel, type MissionViewModel } from "./data/viewModel";
import { useReplayTheater } from "./replay/useReplayTheater";
import { CabinScene } from "./scene/CabinScene";
import { useModalFocus } from "./scene/useModalFocus";

export type PresentationMode = "DEMO" | "LIVE";

const REPLAY_BASE_URL = `${import.meta.env.BASE_URL}demo/approved/`;

type NoticeState = "sentry" | "admiral" | "config" | "logbook" | "market" | null;

export default function App() {
  const [presentationMode, setPresentationMode] = useState<PresentationMode>(() => modeFromSearch(window.location.search));
  const chooseMode = (mode: PresentationMode) => {
    const url = new URL(window.location.href);
    if (mode === "LIVE") url.searchParams.delete("mode");
    else url.searchParams.set("mode", "replay");
    window.history.replaceState(null, "", url);
    setPresentationMode(mode);
  };
  useEffect(() => {
    const followHistory = () => setPresentationMode(modeFromSearch(window.location.search));
    window.addEventListener("popstate", followHistory);
    return () => window.removeEventListener("popstate", followHistory);
  }, []);
  return presentationMode === "LIVE" ? <LiveCabin /> : <ReplayCabin onSelectMode={chooseMode} />;
}

function LiveCabin() {
  const live = useLiveMission();
  if (!live.mission) {
    return (
      <main className="cabin-loading cabin-load-failure" aria-live="polite">
        <p className="eyebrow">BlackPod Battlestar · live read-only</p>
        <h1>{live.status === "LOADING" ? "Connecting to mission evidence…"
          : live.status === "NOT_CONFIGURED" ? "No live mission configured."
          : "Live mission evidence unavailable."}</h1>
        <p>{live.message}</p>
        <p>Start the local reader with an explicit artifacts root and mission ID:</p>
        <pre><code>make cabin-live CABIN_ARTIFACTS_ROOT=/path/to/artifacts CABIN_MISSION_ID=your-mission-id</code></pre>
        <p>No replay data is substituted. This Cabin follows recorded LIVE mission artifacts; it does not run missions or stream prices.</p>
        <p>Read-only · SHADOW only · no approvals, symbol changes, or order execution.</p>
        <div className="load-mode-actions"><button type="button" disabled={live.refreshing} onClick={live.refresh}>Refresh evidence</button></div>
      </main>
    );
  }
  return <MissionCabin key={live.mission.status.missionId} mission={live.mission} presentationMode="LIVE" live={live} />;
}

function ReplayCabin({ onSelectMode }: { onSelectMode: (mode: PresentationMode) => void }) {
  const [mission, setMission] = useState<MissionViewModel | null>(null);
  const [loadError, setLoadError] = useState<{ message: string; fallbackMarkdown: string | null } | null>(null);

  useEffect(() => {
    let active = true;
    setMission(null);
    setLoadError(null);
    loadMissionBundle(REPLAY_BASE_URL)
      .then((bundle) => {
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
  }, []);

  if (loadError) return <LoadFailure mode="DEMO" message={loadError.message} fallbackMarkdown={loadError.fallbackMarkdown} onSelectMode={onSelectMode} />;
  if (!mission) return <LoadingCabin mode="DEMO" />;
  return <MissionCabin mission={mission} presentationMode="DEMO" onSelectMode={onSelectMode} />;
}

function MissionCabin({
  mission,
  presentationMode,
  onSelectMode,
  live,
}: {
  mission: MissionViewModel;
  presentationMode: PresentationMode;
  onSelectMode?: (mode: PresentationMode) => void;
  live?: LiveMissionState & { refresh: () => void };
}) {
  const books = useMemo(() => buildBookDefinitions(mission), [mission]);
  const [selectedBookId, setSelectedBookId] = useState<StageBookId | null>(null);
  const [notice, setNotice] = useState<NoticeState>(null);
  const [activeDestination, setActiveDestination] = useState<CabinDestination>("bridge");
  const [shipFocused, setShipFocused] = useState(false);
  const shipTriggerRef = useRef<HTMLButtonElement>(null);
  const modalTriggerRef = useRef<HTMLElement | null>(null);
  const wasModalOpen = useRef(false);
  const reducedMotion = useReducedMotion();
  const theater = useReplayTheater();
  const currentEntry = theater.revealCount > 0 ? mission.captainsLog[theater.revealCount - 1] : undefined;

  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setSelectedBookId(null);
      setNotice(null);
      setShipFocused(false);
      setActiveDestination("bridge");
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, []);

  const selectedBook = selectedBookId === null ? undefined : books.find((book) => book.id === selectedBookId);
  const shipData = useMemo(() => {
    if (!mission.market.navigatorMarket) return null;
    return mission.market.navigatorMarket;
  }, [mission.market.navigatorMarket]);
  const modalOpen = Boolean(selectedBook || notice || (shipFocused && shipData));

  useLayoutEffect(() => {
    if (wasModalOpen.current && !modalOpen) modalTriggerRef.current?.focus();
    wasModalOpen.current = modalOpen;
  }, [modalOpen]);

  const rememberModalTrigger = (event: ReactMouseEvent<HTMLElement>) => {
    if (modalOpen || !(event.target instanceof Element)) return;
    // Pointer activation does not focus buttons in every browser (notably Safari).
    const trigger = event.target.closest<HTMLElement>("button, a[href]");
    if (trigger && event.currentTarget.contains(trigger)) modalTriggerRef.current = trigger;
  };
  const activeMilestoneBook = milestoneBookId(presentationMode === "LIVE" ? mission.status.currentPhase : theater.currentStage);
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
    <main data-replay-stage={presentationMode === "DEMO" ? theater.currentStage ?? "RESET" : undefined}
      data-current-phase={presentationMode === "LIVE" ? mission.status.currentPhase : undefined} onClickCapture={rememberModalTrigger}>
      <CabinScene
        modalOpen={modalOpen}
        missionBriefHref={`${mission.baseUrl}presentation/mission_brief.html`}
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
          activeMilestone={presentationMode === "LIVE" ? mission.status.currentPhase : currentEntry?.stage ?? null}
          activeStatus={presentationMode === "LIVE" ? mission.status.outcome : currentEntry?.status ?? null}
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
        marketConditions={<MarketConditions symbol={mission.status.symbol} market={mission.market}
          expanded={notice === "market"} onFocus={() => {
            setSelectedBookId(null);
            setShipFocused(false);
            setNotice("market");
          }} />}
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
          triggerRef={shipTriggerRef}
          expanded={shipFocused}
          onOpenShip={() => {
            modalTriggerRef.current = shipTriggerRef.current;
            setShipFocused(true);
          }}
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
        backgroundControls={live ? <LiveEvidenceControls live={live} mission={mission} /> : <>
          <PresentationModeControl mode={presentationMode} runMode={mission.status.runMode} onSelect={onSelectMode!} />
          <ReplayControls theater={theater} announcement={announcement} />
        </>}
        foreground={<>
          {selectedBook ? <BookFocus book={selectedBook} artifactBaseUrl={mission.baseUrl} onClose={closeFocus} /> : null}
          {notice ? <CabinNotice notice={notice} mission={mission} onClose={closeFocus}
            onOpenNavigator={() => { setNotice(null); setShipFocused(true); }} /> : null}
          {shipFocused && shipData ? (
            <NavigatorShipFocus
              data={shipData}
              variants={mission.market.navigatorVariants}
              sourceIdentity={mission.market.sourceIdentity}
              presentationMode={presentationMode}
              runMode={mission.status.runMode}
              capturedAt={mission.market.capturedAt}
              reducedMotion={reducedMotion}
              onClose={closeFocus}
            />
          ) : null}
        </>}
      />
    </main>
  );
}

function LiveEvidenceControls({ live, mission }: { live: LiveMissionState & { refresh: () => void }; mission: MissionViewModel }) {
  const freshness = evidenceFreshness(mission.status.observedAt);
  const status = live.status === "READY" ? freshness : "LAST VERIFIED · READER UNAVAILABLE";
  return <>
    <aside className="presentation-mode-control" aria-label="Live mission reader">
      <strong>LIVE</strong><span>Read-only · {live.status === "READY" ? "reader connected" : "reader unavailable"}</span>
      <button type="button" disabled={live.refreshing} onClick={live.refresh}>Refresh</button>
    </aside>
    <aside className="replay-theater live-evidence-status" aria-label="Mission evidence freshness" aria-live="polite">
      <strong>{status}</strong>
      <span title={`Reader checked: ${live.checkedAt ?? "not yet"}. Browser last verified: ${live.verifiedAt ?? "not yet"}. ${live.message}`}>
        Mission recorded <time dateTime={mission.status.observedAt}>{mission.status.observedAt}</time>
      </span>
      <span>Chart: {mission.market.capturedAt ? `captured ${mission.market.capturedAt.slice(0, 10)}` : "not configured"} · not streaming</span>
    </aside>
  </>;
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
      <span>{runMode} archived review</span>
      <div role="group" aria-label="Select presentation mode">
        <button type="button" aria-pressed={mode === "DEMO"} onClick={() => onSelect("DEMO")}>Demo</button>
        <button type="button" aria-pressed={mode === "LIVE"} onClick={() => onSelect("LIVE")}>Live</button>
      </div>
    </aside>
  );
}

function NavigatorShipFocus({
  data,
  variants,
  sourceIdentity,
  presentationMode,
  runMode,
  capturedAt,
  reducedMotion,
  onClose,
}: {
  data: NavigatorMarket;
  variants?: readonly NavigatorMarketVariant[];
  sourceIdentity: string | null;
  presentationMode: PresentationMode;
  runMode: "LIVE" | "REPLAY";
  capturedAt: string | null;
  reducedMotion: boolean;
  onClose: () => void;
}) {
  const modalFocus = useModalFocus();

  return (
    <div
      {...modalFocus}
      id="navigator-focus"
      className="navigator-focus-layer"
      role="dialog"
      aria-modal="true"
      aria-labelledby="navigator-focus-title"
    >
      <button
        className="book-focus-scrim"
        type="button"
        aria-hidden="true"
        tabIndex={-1}
        onClick={onClose}
      />
      <section className="navigator-focus-surface">
        <header>
          <div>
            <p className="eyebrow">Supplemental read-only Navigator market reference</p>
            <h2 id="navigator-focus-title">Navigator Ship View</h2>
          </div>
          <button type="button" onClick={onClose} autoFocus>Return to bridge</button>
        </header>
        <NavigatorOceanBoundary
          data={data}
          variants={variants}
          sourceIdentity={sourceIdentity}
          presentationMode={presentationMode}
          runMode={runMode}
          capturedAt={capturedAt}
          reducedMotion={reducedMotion}
        />
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

function CabinNotice({ notice, mission, onClose, onOpenNavigator }: {
  notice: Exclude<NoticeState, null>; mission: MissionViewModel; onClose: () => void; onOpenNavigator: () => void;
}) {
  if (notice === "market") {
    return <Notice title="Navigator reference tape" onClose={onClose}>
      <NavigatorReferenceTape mission={mission} onOpenNavigator={onOpenNavigator} />
    </Notice>;
  }
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
        <MissionWarnings warnings={mission.warnings} />
      </Notice>
    );
  }
  return (
    <Notice title={notice === "admiral" ? "Admiral" : "Configuration"} onClose={onClose}>
      <p>{notice === "admiral" ? "Fleet aggregation is not configured. This view follows one explicitly selected mission."
        : "Configure the local mission reader with CABIN_ARTIFACTS_ROOT and CABIN_MISSION_ID, then restart it. Source selection is not editable here."}</p>
      <p>The Captain’s Cabin does not expose settings, approval actions, trading controls, or backend mutation.</p>
      <p>Symbol onboarding and trading integration are future work, not enabled capabilities.</p>
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
  const mode = new URLSearchParams(search).get("mode")?.toLowerCase();
  return mode === "replay" || mode === "demo" ? "DEMO" : "LIVE";
}
