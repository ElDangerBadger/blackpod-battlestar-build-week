import type { PortfolioViewModel } from "../data/viewModel";

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
};

export function SystemsPanel(props: SystemsPanelProps) {
  return (
    <aside className="systems-copy" aria-label="Mission provenance and safety boundary">
      <section className="systems-warnings">
        <h2>{props.presentationMode} mission · warnings</h2>
        {props.warnings.length ? (
          <ul>{props.warnings.slice(0, 3).map((warning) => <li key={warning}>{humanize(warning)}</li>)}</ul>
        ) : <p>None recorded</p>}
      </section>

      <section className="systems-governance">
        <h2>Risk &amp; governance</h2>
        <dl>
          <div><dt>Governor</dt><dd>{props.governorDisposition}</dd></div>
          <div><dt>Operator</dt><dd>{props.operatorResult ?? "Not present"}</dd></div>
          <div><dt>Scope</dt><dd>{props.approvalScope ?? "Not present"}</dd></div>
        </dl>
        <p className="gate-proof"><strong>PROCEED is not approval.</strong><br />The operator gate is a separate canonical event.</p>
      </section>

      <section className="systems-portfolio">
        <h2>Read-only portfolio source</h2>
        {props.portfolio.status === "CAPTURED" ? (
          <>
            <dl>
              <div><dt>Mode</dt><dd>{props.portfolio.mode}</dd></div>
              <div><dt>Source</dt><dd title={props.portfolio.sourceIdentity ?? undefined}>{compact(props.portfolio.sourceIdentity)}</dd></div>
              <div><dt>Captured</dt><dd title={props.portfolio.capturedAt ?? undefined}>{formatObservation(props.portfolio.capturedAt)}</dd></div>
              <div><dt>Positions</dt><dd>{props.portfolio.positionCount}</dd></div>
              <div><dt>Active asset</dt><dd>{props.portfolio.activeExposure.symbol}</dd></div>
              {props.portfolio.activeExposure.status === "POSITION" ? (
                <>
                  <div><dt>Direction</dt><dd>{props.portfolio.activeExposure.direction ?? "Not supplied"}</dd></div>
                  <div><dt>Weight</dt><dd>{formatWeight(props.portfolio.activeExposure.allocationPercent)}</dd></div>
                  <div><dt>Market value</dt><dd>{formatMoney(props.portfolio.activeExposure.marketValue, props.portfolio.activeExposure.currency)}</dd></div>
                </>
              ) : null}
              {props.portfolio.activeExposure.totalExposure !== null ? (
                <div><dt>Total exposure</dt><dd>{formatMoney(props.portfolio.activeExposure.totalExposure, props.portfolio.activeExposure.currency)}</dd></div>
              ) : null}
            </dl>
            {props.portfolio.activeExposure.status === "NO_POSITION" ? (
              <p>No recorded {props.portfolio.activeExposure.symbol} position in the captured snapshot.</p>
            ) : null}
          </>
        ) : <p>Not configured — no illustrative holdings shown.</p>}
      </section>

      <section className="systems-modeldock">
        <h2>Data &amp; model health</h2>
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
        <h2>ModelDock routing</h2>
        <p>Narrative only. Oracle remains authoritative for facts, measurements, diagnostics, and readiness.</p>
      </section>

      <section className="systems-safety">
        <h2>Navigator SHADOW handoff only — no trade or order execution.</h2>
        <div><strong>Allowed</strong> {props.allowedOperations.join(" · ")}</div>
        <div><strong>Prohibited</strong> {props.prohibitedOperations.join(" · ")}</div>
      </section>
    </aside>
  );
}

function formatLatency(value: number | null): string {
  return value === null ? "Not recorded" : `${value.toFixed(0)} ms`;
}

function formatMocked(value: boolean | null): string {
  if (value === null) return "Not recorded";
  return value ? "YES" : "NO";
}

function formatWeight(value: number | null): string {
  return value === null ? "Not supplied" : `${value.toFixed(2)}%`;
}

function formatMoney(value: number | null, currency: string | null): string {
  if (value === null) return "Not supplied";
  if (!currency) return value.toFixed(2);
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: 2 }).format(value);
  } catch {
    return `${value.toFixed(2)} ${currency}`;
  }
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
