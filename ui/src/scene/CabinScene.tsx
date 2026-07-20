import type { CSSProperties, ReactNode } from "react";

import "../styles/cabin.css";
import {
  LOWER_CONTENT_REGIONS,
  SCENE_REGIONS,
  STAGE_BOOK_IDS,
  STAGE_CONTENT_REGIONS,
  regionStyle,
  type SceneRegion,
  type StageBookId,
} from "./layout";

export type CabinBookSlot = {
  id: StageBookId;
  label: string;
  children: ReactNode;
  selected?: boolean;
  revealed?: boolean;
  disabled?: boolean;
  onSelect?: (id: StageBookId) => void;
};

export type CabinSceneProps = {
  status?: ReactNode;
  books?: readonly CabinBookSlot[];
  sentryAlerts?: ReactNode;
  marketConditions?: ReactNode;
  captainsLog?: ReactNode;
  missionChart?: ReactNode;
  paperOrder?: ReactNode;
  systemsPanel?: ReactNode;
  navigation?: ReactNode;
  foreground?: ReactNode;
  className?: string;
  ariaLabel?: string;
  missionBriefHref?: string;
};

type ScenePanelProps = {
  region: SceneRegion;
  className: string;
  label: string;
  children?: ReactNode;
};

function joinClassNames(...names: Array<string | undefined | false>): string {
  return names.filter(Boolean).join(" ");
}

function ScenePanel({ region, className, label, children }: ScenePanelProps) {
  if (children === undefined || children === null) {
    return null;
  }

  return (
    <section
      aria-label={label}
      className={joinClassNames("cabin-region", className)}
      style={regionStyle(region)}
    >
      {children}
    </section>
  );
}

/**
 * Responsive fixed-ratio, data-agnostic shell for the Captain's Cabin. Mission contracts
 * are adapted outside this component and supplied through typed content slots.
 */
export function CabinScene({
  status,
  books = [],
  sentryAlerts,
  marketConditions,
  captainsLog,
  missionChart,
  paperOrder,
  systemsPanel,
  navigation,
  foreground,
  className,
  ariaLabel = "BlackPod Battlestar Captain's Cabin mission presentation",
  missionBriefHref,
}: CabinSceneProps) {
  const bookSlots = new Map(books.map((book) => [book.id, book]));
  const sceneStyle = {
    "--cabin-background": `url("${import.meta.env.BASE_URL}captains-cabin-template.png")`,
  } as CSSProperties;

  return (
    <div className={joinClassNames("cabin-viewport", className)}>
      <section className="cabin-scene" aria-label={ariaLabel} style={sceneStyle}>
        <span className="cabin-scene__description cabin-visually-hidden">
          A read-only mission presentation arranged across five stage books, a Captain&apos;s Log,
          and ship status panels.
        </span>

        <ScenePanel
          region={SCENE_REGIONS["top-status"]}
          className="cabin-status"
          label="Mission status"
        >
          {status}
        </ScenePanel>

        {STAGE_BOOK_IDS.map((bookId) => {
          const slot = bookSlots.get(bookId);
          if (!slot) {
            return null;
          }

          const summaryId = `cabin-${bookId}-summary`;
          const revealed = slot.revealed ?? true;
          const interactive = Boolean(slot.onSelect) && !slot.disabled;

          return (
            <div key={bookId} className="cabin-book">
              {interactive ? (
                <button
                  type="button"
                  className="cabin-region cabin-book__hit-target"
                  style={regionStyle(SCENE_REGIONS[`${bookId}-book`])}
                  aria-label={`Open ${slot.label} book`}
                  aria-describedby={summaryId}
                  aria-pressed={slot.selected ?? false}
                  data-book={bookId}
                  data-revealed={revealed}
                  hidden={!revealed}
                  onClick={() => slot.onSelect?.(bookId)}
                />
              ) : null}

              <article
                id={summaryId}
                aria-label={`${slot.label} summary`}
                className={joinClassNames(
                  "cabin-region",
                  "cabin-book__summary",
                  "stage-copy",
                  slot.selected && "is-selected",
                  !revealed && "is-concealed",
                )}
                style={regionStyle(STAGE_CONTENT_REGIONS[bookId])}
                data-book={bookId}
                data-revealed={revealed}
              >
                {slot.children}
              </article>
            </div>
          );
        })}

        <ScenePanel
          region={LOWER_CONTENT_REGIONS["sentry-alerts"]}
          className="cabin-sentry stage-copy"
          label="Mission alerts"
        >
          {sentryAlerts}
        </ScenePanel>
        <ScenePanel
          region={LOWER_CONTENT_REGIONS["market-conditions"]}
          className="cabin-market stage-copy"
          label="Market conditions"
        >
          {marketConditions}
        </ScenePanel>
        <ScenePanel
          region={LOWER_CONTENT_REGIONS["captains-log"]}
          className="cabin-log captains-log-copy"
          label="Captain's Log"
        >
          {captainsLog}
        </ScenePanel>
        <ScenePanel
          region={LOWER_CONTENT_REGIONS["mission-chart"]}
          className="cabin-chart stage-copy"
          label="Mission chart and evidence"
        >
          {missionChart}
        </ScenePanel>
        <ScenePanel
          region={LOWER_CONTENT_REGIONS["paper-order"]}
          className="cabin-shadow-plan stage-copy"
          label="Navigator SHADOW plan"
        >
          {paperOrder}
        </ScenePanel>
        <ScenePanel
          region={SCENE_REGIONS["systems-panel"]}
          className="cabin-systems"
          label="Mission systems and safety boundary"
        >
          {systemsPanel}
        </ScenePanel>
        <ScenePanel
          region={SCENE_REGIONS["bottom-navigation"]}
          className="cabin-navigation"
          label="Presentation navigation"
        >
          {navigation}
        </ScenePanel>

        {foreground ? <div className="cabin-foreground">{foreground}</div> : null}
      </section>

      {missionBriefHref ? (
        <aside className="cabin-narrow-fallback" aria-label="Narrow screen options">
          <p className="eyebrow">Captain&apos;s Cabin</p>
          <h1>Rotate device</h1>
          <p>The interactive bridge needs a wider viewport to keep every parchment surface aligned.</p>
          <a href={missionBriefHref} target="_blank" rel="noreferrer">
            Open Mission Brief
          </a>
        </aside>
      ) : null}
    </div>
  );
}
