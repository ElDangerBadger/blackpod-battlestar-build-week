import type { ReactNode } from "react";
import type { CabinPanelId } from "./cabinPanelTypes";
import "./panel-triggers.css";

export type StatusPanelProps = {
  presentationMode: "DEMO" | "LIVE";
  symbol: string;
  companyName: string | null;
  timeframe: string | null;
  marketStatus: string | null;
  latestCompletedBar: string | null;
  mode: string;
  outcome: string;
  phase: string;
  missionId: string;
  timestamp: string;
  approvalScope: string | null;
  snapshotCount: number;
  modeldockMode: string;
  modeldockStatus: string;
  activeMilestone: string | null;
  activeStatus: string | null;
  onExpand?: (panel: CabinPanelId) => void;
  activePanel?: CabinPanelId | null;
};

export function StatusPanel(props: StatusPanelProps) {
  return (
    <section className="status-panel" aria-label="Canonical mission status">
      <StatusCell
        panel="market" openLabel="Open market context" onExpand={props.onExpand} activePanel={props.activePanel}
        className="status-market"
        label={`Mission symbol · ${props.presentationMode}`}
        value={`${props.symbol} · correlation`}
        detail={props.companyName
          ? `Navigator reference: ${props.companyName} · ${props.timeframe ?? "frame not recorded"}`
          : `${props.mode} source · security context not recorded`}
      />
      <StatusCell
        panel="fleet" openLabel="Open fleet status" onExpand={props.onExpand} activePanel={props.activePanel}
        className="status-fleet"
        label="Outcome / phase"
        value={`${props.outcome} · ${props.phase}`}
      />
      <StatusCell
        panel="modeldock" openLabel="Open ModelDock provenance" onExpand={props.onExpand} activePanel={props.activePanel}
        className="status-modeldock"
        label="ModelDock"
        value={`${props.modeldockMode} · ${props.modeldockStatus}`}
      />
      <StatusCell
        panel="timeframe" openLabel="Open timeframe details" onExpand={props.onExpand} activePanel={props.activePanel}
        className="status-count"
        label="Timeframe"
        value={props.timeframe ?? "N/A"}
        detail={`${props.snapshotCount} ${props.snapshotCount === 1 ? "snapshot" : "snapshots"}`}
      />
      <StatusCell
        panel="mission" openLabel="Open mission details" onExpand={props.onExpand} activePanel={props.activePanel}
        className="status-mission"
        label="Mission ID"
        value={props.missionId}
        detail={props.activeMilestone ? `${props.activeMilestone} · ${props.activeStatus}` : "Ready to replay"}
        title={props.missionId}
      />
      <StatusCell
        panel="market-timing" openLabel="Open market timing" onExpand={props.onExpand} activePanel={props.activePanel}
        className="status-shadow"
        label="Market / latest bar"
        value={props.marketStatus ?? "Not recorded"}
        detail={props.latestCompletedBar ? formatBarTimestamp(props.latestCompletedBar) : "Bar not recorded"}
      />
      <StatusCell
        panel="mission-time" openLabel="Open mission time" onExpand={props.onExpand} activePanel={props.activePanel}
        className="status-time"
        label="Mission time"
        value={formatDate(props.timestamp)}
        detail={formatClock(props.timestamp)}
      />
      <StatusCell
        panel="approval" openLabel="Open approval scope" onExpand={props.onExpand} activePanel={props.activePanel}
        className="status-scope"
        label="Approval scope"
        value={props.approvalScope ?? "Not present"}
        title={props.approvalScope ?? undefined}
      />
      <span className="status-canonical sr-only">Mission ID {props.missionId}.</span>
    </section>
  );
}

type StatusCellProps = {
  className: string;
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  title?: string;
  panel: CabinPanelId;
  openLabel: string;
  onExpand?: (panel: CabinPanelId) => void;
  activePanel?: CabinPanelId | null;
};

function StatusCell({ className, label, value, detail, title, panel, openLabel, onExpand, activePanel }: StatusCellProps) {
  return (
    <div className={`status-cell ${className}${onExpand ? " cabin-panel-expandable" : ""}`} title={title}>
      <span>{label}</span>
      <strong>{value}</strong>
      {detail ? <em>{detail}</em> : null}
      {onExpand ? <button
        className="cabin-panel-trigger"
        type="button"
        aria-label={openLabel}
        aria-haspopup="dialog"
        aria-expanded={activePanel === panel}
        onClick={() => onExpand(panel)}
      ><span className="cabin-panel-open-cue" aria-hidden="true">Open ↗</span></button> : null}
    </div>
  );
}

function formatClock(timestamp: string): string {
  const match = timestamp.match(/T(\d{2}:\d{2})(?::\d{2}(?:\.\d+)?)?Z$/);
  return match ? `${match[1]} UTC` : timestamp;
}

function formatDate(timestamp: string): string {
  return /^\d{4}-\d{2}-\d{2}T/.test(timestamp) ? timestamp.slice(0, 10) : timestamp;
}

function formatBarTimestamp(timestamp: string): string {
  const date = formatDate(timestamp);
  const clock = timestamp.match(/T(\d{2}:\d{2})/)?.[1];
  return clock && clock !== "00:00" ? `${date} ${clock}Z` : date;
}
