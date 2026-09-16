type WarningExplanation = Readonly<{ title: string; meaning: string; impact: string }>;

/** Allowlisted explanations only: unknown warnings retain their recorded text. */
export function explainMissionWarning(warning: string): WarningExplanation {
  const excluded = "EXCLUDED_ORACLE_SNAPSHOT_SYMBOLS:";
  if (warning.startsWith(excluded) && warning.slice(excluded.length).trim()) {
    return {
      title: "Some symbols were left out of Oracle's analysis",
      meaning: `Excluded symbols: ${warning.slice(excluded.length).split(",").join(", ")}.`,
      impact: "The recorded Oracle measurements do not cover these symbols. This warning alone does not say why each was excluded.",
    };
  }
  if (warning === "MISSING_PRIOR_ORACLE_MEASUREMENTS") {
    return {
      title: "The prior Oracle comparison is unavailable",
      meaning: "No usable earlier measurement comparison is recorded for this run.",
      impact: "Changes that require that earlier comparison are unavailable. This does not mean all current measurements are missing.",
    };
  }
  if (warning === "READ_ONLY_DATA_RUN_NO_TRADING_AUTHORITY"
    || warning === "Mandate is valid but does not permit action: READ_ONLY_DATA_RUN_NO_TRADING_AUTHORITY") {
    return {
      title: "This mission was authorized for analysis only",
      meaning: "The recorded mandate is valid, but it grants no trading authority.",
      impact: "Council and Governor can record their reviews, but this mandate does not permit a trade. A blocked action decision is not itself a processing failure.",
    };
  }
  return {
    title: "Additional recorded warning",
    meaning: warning,
    impact: "No plain-language explanation is mapped for this warning. Its original wording is preserved below.",
  };
}

export function MissionWarnings({ warnings }: { warnings: readonly string[] }) {
  if (!warnings.length) return <p>No warnings are recorded in this mission.</p>;
  return <div className="mission-warnings-readable">
    <p className="notice-lede">{warnings.length} recorded {warnings.length === 1 ? "notice" : "notices"} to understand before reading this mission's results.</p>
    <p>Warnings can describe data coverage or permission limits; they do not all mean the software failed.</p>
    <ol className="mission-warning-list">
      {warnings.map((warning, index) => {
        const explanation = explainMissionWarning(warning);
        return <li key={`${index}-${warning}`}>
          <h3>{explanation.title}</h3>
          <p>{explanation.meaning}</p>
          <p><strong>What this means for the record:</strong> {explanation.impact}</p>
          <details className="recorded-details"><summary>Original warning · exact wording</summary><code>{warning}</code></details>
        </li>;
      })}
    </ol>
    <p className="notice-note">These explanations are presentation guidance derived from the saved warnings. They do not change the mission's evidence, decision, or permissions.</p>
  </div>;
}
