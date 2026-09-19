import { createOracleOverview, type OracleSymbolRow } from "../data/oracleOverview";
import type { MissionViewModel } from "../data/viewModel";

const COVERAGE: Record<OracleSymbolRow["coverage"], string> = {
  used: "Included in measurements", excluded: "Excluded from measurements",
  missing: "Missing input", "not-recorded": "Coverage not recorded", conflicting: "Conflicting coverage",
};

function RecordedTime({ value }: { value: string | null }) {
  if (!value) return <>Not recorded</>;
  if (!Number.isFinite(Date.parse(value))) return <>{value}</>;
  const formatted = new Intl.DateTimeFormat("en-US", {
    month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit",
    timeZone: "UTC", timeZoneName: "short",
  }).format(new Date(value));
  return <time dateTime={value} title={value}>{formatted}</time>;
}

function RecordedNumber({ value, percent = false }: { value: number | null; percent?: boolean }) {
  if (value === null) return <>Not recorded</>;
  // Formatting only: normalized return_pct is already percentage points.
  return <span title={`Exact recorded value: ${value}`}>{value.toLocaleString("en-US", {
    maximumFractionDigits: percent ? 4 : 6,
  })}{percent ? "%" : ""}</span>;
}

/** Display supplied measurements and snapshot values; never score or rank symbols. */
export function OracleOverview({ viewModel }: { viewModel: MissionViewModel }) {
  const overview = createOracleOverview(viewModel);
  return <section className="oracle-overview" aria-label="Oracle measurements and market coverage">
    <h4>Recorded market measurements</h4>
    <p>Market snapshot: <RecordedTime value={overview.asOf} />. These are saved Oracle measurements, not live prices or a new browser analysis.</p>
    {overview.issues.length ? <aside className="oracle-overview-limits" aria-label="Oracle evidence alignment limits">
      <ul>{overview.issues.map((issue) => <li key={issue}>{issue}</li>)}</ul>
    </aside> : null}
    <dl className="oracle-measurement-cards">{overview.measurements.map((measurement) => <div key={measurement.key}>
      <dt>{measurement.label}</dt>
      <dd>
        <strong className="oracle-measurement-value">{measurement.value === null ? "Unavailable" : String(measurement.value)}</strong>
        <p>{measurement.meaning}</p>
        {measurement.unavailableReason ? <p className="oracle-overview-limits">{measurement.unavailableReason}
          {measurement.rawValue !== null ? <> Recorded raw value: <code>{String(measurement.rawValue)}</code>; not interpreted as a measured result.</> : null}
        </p> : null}
      </dd>
    </div>)}</dl>
    <h4>Sector and index observations</h4>
    <p>Groups and order come from Oracle’s recorded policy. Returns are the supplied change from previous close; they are not leadership rankings. Observed but excluded instruments remain separate.</p>
    {!overview.groups.some((group) => group.rows.length) ? <p>No source-aligned symbol observations are available in this evidence.</p> : null}
    {overview.groups.filter((group) => group.rows.length).map((group) => <div className="oracle-table-scroll" key={group.id}>
      <table className="oracle-observation-table">
        <caption>{group.label}</caption>
        <thead><tr><th scope="col">Symbol</th><th scope="col">Recorded return</th><th scope="col">Recorded price</th><th scope="col">Oracle coverage</th><th scope="col">Observation time</th></tr></thead>
        <tbody>{group.rows.map((row) => <tr key={row.symbol}>
          <th scope="row">{row.symbol}</th><td><RecordedNumber value={row.returnPct} percent /></td>
          <td><RecordedNumber value={row.price} /></td><td>{COVERAGE[row.coverage]}</td><td><RecordedTime value={row.timestamp} /></td>
        </tr>)}</tbody>
      </table>
    </div>)}
    <p className="book-note">Recorded policy: <code>{overview.policy ?? "Not recorded"}</code>. Prices retain source units; currency is not inferred. Exclusion is not automatically a failed provider request.</p>
    <details className="oracle-source-identities"><summary>Measurement source identities</summary>
      <dl><dt>Measurement</dt><dd>{overview.measurementId ?? "Not recorded"}</dd><dt>Normalized snapshot</dt><dd>{overview.normalizedSnapshotId ?? "Not recorded"}</dd></dl>
    </details>
  </section>;
}

/** Per-symbol diagnostics are copied from aligned evidence, including exclusions. */
export function OracleDiagnostics({ viewModel }: { viewModel: MissionViewModel }) {
  const overview = createOracleOverview(viewModel);
  const rows = overview.groups.flatMap((group) => group.rows);
  return <section className="oracle-overview" aria-label="Oracle per-symbol diagnostics">
    <h4>What happened to each input?</h4>
    <p>Included means Oracle used this input—not that an instrument is suitable for a trade. A fallback describes a supplied alternate input, not a browser repair.</p>
    {overview.issues.length ? <ul className="oracle-overview-limits">{overview.issues.map((issue) => <li key={issue}>{issue}</li>)}</ul> : null}
    {rows.length ? <div className="oracle-table-scroll"><table className="oracle-observation-table">
      <caption>Recorded symbol diagnostics</caption>
      <thead><tr><th scope="col">Symbol</th><th scope="col">Coverage / status</th><th scope="col">Return source / fallback</th><th scope="col">Recorded limits</th></tr></thead>
      <tbody>{rows.map((row) => <tr key={row.symbol}>
        <th scope="row">{row.symbol}</th><td>{COVERAGE[row.coverage]}<br />Status: {row.diagnosticStatus ?? "Not recorded"}</td>
        <td>{row.returnSource ?? "Return source not recorded"}<br />{row.usedFallback === null ? "Fallback status not recorded" : row.usedFallback ? "Fallback used" : "No fallback recorded"}
          {row.fallbackReason ? <p>{row.fallbackReason}</p> : null}</td>
        <td>{row.diagnosticStatus === null ? "Diagnostics unavailable" : !row.warnings.length && !row.blockers.length ? "No symbol-level limits listed" : <ul>
          {row.warnings.map((warning) => <li key={`warning-${warning}`}>Warning: {warning}</li>)}
          {row.blockers.map((blocker) => <li key={`blocker-${blocker}`}>Blocker: {blocker}</li>)}
        </ul>}</td>
      </tr>)}</tbody>
    </table></div> : <p>No source-aligned per-symbol diagnostics are available.</p>}
    <p className="book-note">Diagnostic receipt: <code>{overview.diagnosticsId ?? "Not recorded"}</code>. Overall readiness and market coverage are separate: READY does not mean every observed symbol was measured.</p>
  </section>;
}
