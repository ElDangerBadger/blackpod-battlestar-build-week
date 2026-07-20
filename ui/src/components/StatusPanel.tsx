import type { ReactNode } from "react";

export type StatusPanelProps = {
  symbol: string;
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
};

export function StatusPanel(props: StatusPanelProps) {
  return (
    <section className="status-panel" aria-label="Canonical mission status">
      <StatusCell
        className="status-market"
        label="Mission"
        value={`${props.symbol} · ${props.mode}`}
      />
      <StatusCell
        className="status-fleet"
        label="Outcome / phase"
        value={`${props.outcome} · ${props.phase}`}
      />
      <StatusCell
        className="status-modeldock"
        label="ModelDock"
        value={`${props.modeldockMode} · ${props.modeldockStatus}`}
      />
      <StatusCell className="status-count" label="Snapshots" value={String(props.snapshotCount)} />
      <StatusCell
        className="status-mission"
        label="Mission ID"
        value={props.missionId}
        detail={props.activeMilestone ? `${props.activeMilestone} · ${props.activeStatus}` : "Ready to replay"}
        title={props.missionId}
      />
      <StatusCell className="status-shadow" label="Navigator mode" value="SHADOW" />
      <StatusCell className="status-time" label="Canonical time" value={formatTimestamp(props.timestamp)} />
      <StatusCell
        className="status-scope"
        label="Approval scope"
        value={props.approvalScope ?? "Not present"}
        title={props.approvalScope ?? undefined}
      />
      <span className="status-canonical sr-only">Mission ID {props.missionId}.</span>
    </section>
  );
}

function StatusCell({ className, label, value, detail, title }: { className: string; label: string; value: ReactNode; detail?: ReactNode; title?: string }) {
  return (
    <div className={`status-cell ${className}`} title={title}>
      <span>{label}</span>
      <strong>{value}</strong>
      {detail ? <em>{detail}</em> : null}
    </div>
  );
}

function formatTimestamp(timestamp: string): string {
  const match = timestamp.match(/T(\d{2}:\d{2})(?::\d{2})?Z$/);
  return match ? `${match[1]} UTC` : timestamp;
}
