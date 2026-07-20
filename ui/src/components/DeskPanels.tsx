export function SentryAlerts({ warnings, onFocus }: { warnings: readonly string[]; onFocus: () => void }) {
  return (
    <button className="loose-paper sentry-copy" type="button" onClick={onFocus} aria-label="Focus mission warnings">
      <span className="paper-title">Mission warnings</span>
      {warnings.length ? warnings.slice(0, 3).map((warning) => (
        <span key={warning} title={warning}>{warningForDesk(warning)}</span>
      )) : <span>None recorded</span>}
    </button>
  );
}

function warningForDesk(warning: string): string {
  if (warning.startsWith("EXCLUDED_ORACLE_SNAPSHOT_SYMBOLS:")) {
    const symbols = warning.split(":", 2)[1]?.split(",").join(" · ") ?? "Not recorded";
    return `Excluded validation symbols: ${symbols}`;
  }
  if (warning === "MISSING_PRIOR_ORACLE_MEASUREMENTS") {
    return "Prior Oracle measurements unavailable";
  }
  return warning.replaceAll("_", " ").replaceAll(",", ", ");
}

export function MarketConditions() {
  return (
    <section className="loose-paper market-copy" aria-label="Market conditions">
      <span className="paper-title">Market conditions</span>
      <p>Security-specific market tape is not present in this mission artifact.</p>
    </section>
  );
}

export function MissionChart({ missionId, snapshotCount, revision }: { missionId: string; snapshotCount: number; revision: number }) {
  return (
    <section className="chart-copy" aria-label="Mission evidence chart">
      <span className="paper-title">Mission chart</span>
      <p>{missionId}</p>
      <div className="route-line" aria-hidden="true"><i /><i /><i /><i /><i /></div>
      <dl>
        <div><dt>Snapshots</dt><dd>{snapshotCount}</dd></div>
        <div><dt>Final revision</dt><dd>r{String(revision).padStart(4, "0")}</dd></div>
        <div><dt>Integrity</dt><dd>Hash-linked</dd></div>
      </dl>
    </section>
  );
}

export function ShadowPlanPaper({ allowed, prohibited, outcome }: { allowed: readonly string[]; prohibited: readonly string[]; outcome: string }) {
  return (
    <section className="paper-order-copy" aria-label="Navigator SHADOW plan boundary">
      <span className="paper-title">Shadow plan</span>
      <strong>NO ORDER CREATED</strong>
      <dl>
        <div><dt>Outcome</dt><dd>{outcome}</dd></div>
        <div><dt>Mode</dt><dd>SHADOW</dd></div>
        <div><dt>Allowed</dt><dd>{allowed.join(" · ")}</dd></div>
      </dl>
      <p>Prohibited: {prohibited.join(" · ")}</p>
    </section>
  );
}
