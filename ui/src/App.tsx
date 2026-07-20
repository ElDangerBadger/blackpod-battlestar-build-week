import { useEffect, useMemo, useState } from "react";

import { BookFocus } from "./books/BookFocus";
import { buildBookDefinitions, type BookDefinition, type StageBookId } from "./books/bookPages";
import { BottomNavigation, type CabinDestination } from "./components/BottomNavigation";
import { CaptainsLog } from "./components/CaptainsLog";
import { MarketConditions, MissionChart, SentryAlerts, ShadowPlanPaper } from "./components/DeskPanels";
import { Notice } from "./components/Notice";
import { ReplayControls } from "./components/ReplayControls";
import { StatusPanel } from "./components/StatusPanel";
import { SystemsPanel } from "./components/SystemsPanel";
import { loadMissionBundle, MissionBundleLoadError } from "./data/loadMission";
import { createMissionViewModel, type MissionViewModel } from "./data/viewModel";
import { useReplayTheater } from "./replay/useReplayTheater";
import { CabinScene } from "./scene/CabinScene";

const DEMO_BASE_URL = `${import.meta.env.BASE_URL}demo/approved/`;
const MISSION_BRIEF_URL = `${DEMO_BASE_URL}presentation/mission_brief.html`;

type NoticeState = "sentry" | "admiral" | "config" | "logbook" | null;

export default function App() {
  const [mission, setMission] = useState<MissionViewModel | null>(null);
  const [loadError, setLoadError] = useState<{ message: string; fallbackMarkdown: string | null } | null>(null);

  useEffect(() => {
    let active = true;
    loadMissionBundle(DEMO_BASE_URL)
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

  if (loadError) return <LoadFailure message={loadError.message} fallbackMarkdown={loadError.fallbackMarkdown} />;
  if (!mission) return <LoadingCabin />;
  return <MissionCabin mission={mission} />;
}

function MissionCabin({ mission }: { mission: MissionViewModel }) {
  const books = useMemo(() => buildBookDefinitions(mission), [mission]);
  const [selectedBookId, setSelectedBookId] = useState<StageBookId | null>(null);
  const [notice, setNotice] = useState<NoticeState>(null);
  const [activeDestination, setActiveDestination] = useState<CabinDestination>("bridge");
  const theater = useReplayTheater();
  const currentEntry = theater.revealCount > 0 ? mission.captainsLog[theater.revealCount - 1] : undefined;

  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setSelectedBookId(null);
      setNotice(null);
      setActiveDestination("bridge");
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, []);

  const selectedBook = selectedBookId === null ? undefined : books.find((book) => book.id === selectedBookId);
  const activeMilestoneBook = milestoneBookId(theater.currentStage);
  const announcement = currentEntry
    ? `${currentEntry.stage}: ${currentEntry.status}. ${currentEntry.summary}`
    : "Mission replay reset. No stage has been revealed.";

  const selectBook = (id: StageBookId) => {
    setNotice(null);
    setSelectedBookId(id);
    setActiveDestination(destinationForBook(id));
  };

  const closeFocus = () => {
    setSelectedBookId(null);
    setNotice(null);
    setActiveDestination("bridge");
  };

  const navigate = (destination: CabinDestination) => {
    setActiveDestination(destination);
    setSelectedBookId(null);
    setNotice(null);
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
        missionBriefHref={MISSION_BRIEF_URL}
        status={<StatusPanel
          symbol={mission.status.symbol}
          mode={mission.status.runMode}
          outcome={mission.status.outcome}
          phase={mission.status.currentPhase}
          missionId={mission.status.missionId}
          timestamp={mission.status.generatedAt}
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
        marketConditions={<MarketConditions />}
        captainsLog={<CaptainsLog
          entries={mission.captainsLog}
          revealedStages={theater.revealed}
          onFocus={() => navigate("logbook")}
        />}
        missionChart={<MissionChart
          missionId={mission.status.missionId}
          snapshotCount={mission.status.snapshotCount}
          revision={mission.status.snapshotCount}
        />}
        paperOrder={navigatorRevealed
          ? <ShadowPlanPaper
              allowed={mission.safety.allowedOperations}
              prohibited={mission.safety.prohibitedOperations}
              outcome={missionRevealed ? mission.status.outcome : "AWAITING MISSION REVEAL"}
            />
          : <AwaitingShadowPlan />}
        systemsPanel={<SystemsPanel
          warnings={theater.revealed.has("ORACLE") ? mission.warnings : []}
          governorDisposition={governorRevealed ? mission.status.governorDisposition ?? "Not present" : "Awaiting reveal"}
          operatorResult={operatorRevealed ? mission.status.operatorResult : "Awaiting reveal"}
          approvalScope={missionRevealed ? mission.status.approvalScope : "Awaiting mission reveal"}
          modeldockMode={modeldockRevealed ? mission.modeldock.mode : "Awaiting reveal"}
          provider={modeldockRevealed ? mission.modeldock.provider : null}
          model={modeldockRevealed ? mission.modeldock.model : null}
          traceId={modeldockRevealed ? mission.modeldock.traceId : null}
          allowedOperations={mission.safety.allowedOperations}
          prohibitedOperations={mission.safety.prohibitedOperations}
        />}
        navigation={<BottomNavigation active={activeDestination} onNavigate={navigate} />}
        foreground={<>
          <ReplayControls theater={theater} announcement={announcement} />
          {selectedBook ? <BookFocus book={selectedBook} artifactBaseUrl={mission.baseUrl} onClose={closeFocus} /> : null}
          {notice ? <CabinNotice notice={notice} mission={mission} onClose={closeFocus} /> : null}
        </>}
      />
    </main>
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

function AwaitingShadowPlan() {
  return (
    <section className="paper-order-copy" aria-label="Navigator SHADOW plan pending reveal">
      <span className="paper-title">Shadow plan</span>
      <strong>NO ORDER EXECUTION</strong>
      <p>Awaiting canonical Navigator evidence in mission replay.</p>
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

function LoadingCabin() {
  return (
    <main className="cabin-loading" aria-live="polite">
      <p className="eyebrow">BlackPod Battlestar</p>
      <h1>Opening the Captain’s Cabin…</h1>
      <p>Validating canonical mission artifacts and evidence hashes.</p>
    </main>
  );
}

function LoadFailure({ message, fallbackMarkdown }: { message: string; fallbackMarkdown: string | null }) {
  return (
    <main className="cabin-loading cabin-load-failure" role="alert">
      <p className="eyebrow">Captain’s Cabin unavailable</p>
      <h1>Mission evidence could not be validated.</h1>
      <p>{message}</p>
      <p>Run <code>make cabin-prepare</code>, then reload this read-only presentation.</p>
      {fallbackMarkdown ? (
        <details className="captains-log-fallback">
          <summary>Read Captain’s Log Markdown fallback</summary>
          <pre>{fallbackMarkdown}</pre>
        </details>
      ) : null}
    </main>
  );
}
