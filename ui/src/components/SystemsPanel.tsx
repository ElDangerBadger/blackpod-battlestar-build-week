export type SystemsPanelProps = {
  warnings: readonly string[];
  governorDisposition: string;
  operatorResult: string | null;
  approvalScope: string | null;
  modeldockMode: string;
  provider: string | null;
  model: string | null;
  traceId: string | null;
  allowedOperations: readonly string[];
  prohibitedOperations: readonly string[];
};

export function SystemsPanel(props: SystemsPanelProps) {
  return (
    <aside className="systems-copy" aria-label="Mission provenance and safety boundary">
      <section className="systems-warnings">
        <h2>Mission warnings</h2>
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

      <section className="systems-modeldock">
        <h2>Data &amp; model health</h2>
        <dl>
          <div><dt>Mode</dt><dd>{props.modeldockMode}</dd></div>
          <div><dt>Provider</dt><dd>{props.provider ?? "Not present"}</dd></div>
          <div><dt>Model</dt><dd title={props.model ?? undefined}>{compact(props.model)}</dd></div>
          <div><dt>Trace</dt><dd title={props.traceId ?? undefined}>{compact(props.traceId)}</dd></div>
        </dl>
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
