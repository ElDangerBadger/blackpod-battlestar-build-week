import type { PortfolioViewModel } from "../data/viewModel";
import type { CabinPanelId } from "./cabinPanelTypes";
import "./panel-triggers.css";

export type SystemsPanelProps = {
  presentationMode: "DEMO" | "LIVE";
  warnings: readonly string[];
  governorDisposition: string;
  operatorResult: string | null;
  approvalScope: string | null;
  modeldockMode: string;
  provider: string | null;
  model: string | null;
  traceId: string | null;
  latencyMs: number | null;
  lastSuccessfulInference: string | null;
  modeldockAvailability: string;
  mocked: boolean | null;
  portfolio: PortfolioViewModel;
  allowedOperations: readonly string[];
  prohibitedOperations: readonly string[];
  onExpand?: (panel: CabinPanelId) => void;
  activePanel?: CabinPanelId | null;
};

export function SystemsPanel(props: SystemsPanelProps) {
  return (
    <aside className="systems-copy" aria-label="Mission provenance and safety boundary">
      <section className="systems-warnings">
        <PanelTrigger panel="watchlist" label="Open watchlist and warnings" onExpand={props.onExpand} activePanel={props.activePanel} />
        <h2>{props.presentationMode} mission · warnings</h2>
        {props.warnings.length ? (
          <ul>{props.warnings.slice(0, 3).map((warning) => <li key={warning}>{humanize(warning)}</li>)}</ul>
        ) : <p>None recorded</p>}
      </section>

      <section className="systems-governance">
        <PanelTrigger panel="governance" label="Open risk and governance" onExpand={props.onExpand} activePanel={props.activePanel} />
        <h2>Risk &amp; governance</h2>
        <dl>
          <div><dt>Governor</dt><dd title={props.governorDisposition}>{props.governorDisposition}</dd></div>
          <div><dt>Operator</dt><dd title={props.operatorResult ?? undefined}>{props.operatorResult ?? "Not present"}</dd></div>
          <div><dt>Scope</dt><dd title={props.approvalScope ?? undefined}>{props.approvalScope ?? "Not present"}</dd></div>
        </dl>
        <p className="gate-proof"><strong>PROCEED is not approval.</strong><br />The operator gate is a separate canonical event.</p>
      </section>

      <section className="systems-governor-record">
        <PanelTrigger panel="governor" label="Open Governor disposition" onExpand={props.onExpand} activePanel={props.activePanel} />
        <h2>Recorded Governor disposition</h2>
        <p>{props.governorDisposition}</p>
        <p>No execution authority.</p>
      </section>

      <section className="systems-portfolio">
        <PanelTrigger panel="portfolio" label="Open portfolio exposure" onExpand={props.onExpand} activePanel={props.activePanel} />
        <h2>Read-only portfolio source</h2>
        {props.portfolio.status === "CAPTURED" ? (
          <dl>
            <div><dt>Mode</dt><dd>{props.portfolio.mode}</dd></div>
            <div><dt>Source</dt><dd title={props.portfolio.sourceIdentity ?? undefined}>{compact(props.portfolio.sourceIdentity)}</dd></div>
            <div><dt>Captured</dt><dd title={props.portfolio.capturedAt ?? undefined}>{formatObservation(props.portfolio.capturedAt)}</dd></div>
            <div><dt>Positions</dt><dd>{props.portfolio.positionCount}</dd></div>
          </dl>
        ) : <p>Not configured — no illustrative holdings shown.</p>}
      </section>

      <section className="systems-modeldock">
        <PanelTrigger panel="modeldock" label="Open ModelDock provenance" onExpand={props.onExpand} activePanel={props.activePanel} />
        <h2>Recorded model provenance</h2>
        <dl>
          <div><dt>Mode</dt><dd>{props.modeldockMode}</dd></div>
          <div><dt>Provider</dt><dd>{props.provider ?? "Not present"}</dd></div>
          <div><dt>Model</dt><dd title={props.model ?? undefined}>{compact(props.model)}</dd></div>
          <div><dt>Trace</dt><dd title={props.traceId ?? undefined}>{compact(props.traceId)}</dd></div>
          <div><dt>Latency</dt><dd>{formatLatency(props.latencyMs)}</dd></div>
          <div><dt>Last inference</dt><dd title={props.lastSuccessfulInference ?? undefined}>{formatObservation(props.lastSuccessfulInference)}</dd></div>
          <div><dt>Mocked</dt><dd>{formatMocked(props.mocked)}</dd></div>
        </dl>
        <p title={props.lastSuccessfulInference ?? undefined}>{props.modeldockAvailability}</p>
      </section>

      <section className="systems-authority">
        <PanelTrigger panel="model-routing" label="Open model routing" onExpand={props.onExpand} activePanel={props.activePanel} />
        <h2>ModelDock routing</h2>
        <p>Narrative only. Oracle remains authoritative for facts, measurements, diagnostics, and readiness.</p>
      </section>

      <section className="systems-safety">
        <PanelTrigger panel="safety" label="Open safety boundary" onExpand={props.onExpand} activePanel={props.activePanel} />
        <h2>Navigator SHADOW handoff only — no trade or order execution.</h2>
        <div><strong>Allowed</strong> {props.allowedOperations.join(" · ")}</div>
        <div><strong>Prohibited</strong> {props.prohibitedOperations.join(" · ")}</div>
      </section>
    </aside>
  );
}

function PanelTrigger({ panel, label, onExpand, activePanel }: {
  panel: CabinPanelId;
  label: string;
  onExpand?: (panel: CabinPanelId) => void;
  activePanel?: CabinPanelId | null;
}) {
  if (!onExpand) return null;
  return <button
    className="cabin-panel-trigger"
    type="button"
    aria-label={label}
    aria-haspopup="dialog"
    aria-expanded={activePanel === panel}
    onClick={() => onExpand(panel)}
  ><span className="cabin-panel-open-cue" aria-hidden="true">Open ↗</span></button>;
}

function formatLatency(value: number | null): string {
  return value === null ? "Not recorded" : `${value.toFixed(0)} ms`;
}

function formatMocked(value: boolean | null): string {
  if (value === null) return "Not recorded";
  return value ? "YES" : "NO";
}

function formatObservation(value: string | null): string {
  if (!value) return "Not recorded";
  const match = value.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/);
  return match ? `${match[1]} ${match[2]}Z` : compact(value);
}

function compact(value: string | null): string {
  if (!value) return "Not present";
  return value.length > 27 ? `${value.slice(0, 24)}…` : value;
}

function humanize(value: string): string {
  return value
    .replaceAll("_", " ")
    .replaceAll(":", ": ")
    .replace(/,(?=\S)/g, ", ");
}
