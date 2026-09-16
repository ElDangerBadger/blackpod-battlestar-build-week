import type { JsonObject } from "../contracts/presentation";
import { explainMissionWarning } from "../components/MissionWarnings";
import { missionRelativeUrl, type MissionEvidenceName } from "../data/loadMission";
import { getObject, getString, getStringArray, isMissionRelativePath } from "../data/validate";
import { getEvidence, type MissionViewModel } from "../data/viewModel";

const COMMENTARY = [
  ["breadth_commentary", "Market participation"],
  ["leadership_commentary", "Leadership"],
  ["rotation_commentary", "Sector rotation"],
  ["risk_regime_commentary", "Risk posture"],
] as const;
const FACT_SOURCES: readonly string[] = [
  "oracle_measurements", "oracle_measurement_diagnostics", "oracle_readiness_report", "oracle_assessment", "oracle_report",
];

function loaded(viewModel: MissionViewModel, name: MissionEvidenceName): JsonObject | undefined {
  const evidence = getEvidence(viewModel, name);
  return evidence?.status === "LOADED" ? evidence.document ?? undefined : undefined;
}

function hasNarrative(document: JsonObject | undefined): document is JsonObject {
  return Boolean(getString(document?.summary) || COMMENTARY.some(([key]) => getString(document?.[key])));
}

function recordedTime(value: string): string {
  if (!Number.isFinite(Date.parse(value))) return value;
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC", timeZoneName: "short",
  }).format(new Date(value));
}

function NarrativeWarnings({ documents }: { documents: readonly (JsonObject | undefined)[] }) {
  const values = [...new Set(documents.flatMap((document) => getStringArray(document?.warnings) ?? []))];
  if (!values.length) return null;
  return <aside className="oracle-narrative-limits" aria-label="Recorded narrative limitations">
    <h4>Limits on this reading</h4>
    <ul>{values.map((warning) => {
      const explanation = explainMissionWarning(warning);
      return <li key={warning}>{explanation.meaning} {explanation.impact}</li>;
    })}</ul>
  </aside>;
}

/** Recorded prose, not a browser synthesis or a new ModelDock request. */
export function OracleMarketNarrative({ viewModel }: { viewModel: MissionViewModel }) {
  const report = loaded(viewModel, "oracle_report");
  const native = loaded(viewModel, "oracle_narrative");
  const embedded = getObject(report?.narrative_summary);
  const mismatch = Boolean(report && native && ["narrative_id", "assessment_id"].some((key) => {
    const expected = getString(report[key]);
    return expected !== undefined && expected !== getString(native[key]);
  }));
  // Do not splice partially populated prose from different source documents.
  const source = hasNarrative(embedded) ? embedded : !mismatch && hasNarrative(native) ? native : undefined;
  const fromReport = source === embedded && source !== undefined;
  const summaryOnly = !source && getString(report?.summary);
  const asOf = getString((fromReport || summaryOnly ? report : native)?.as_of)
    ?? getString((fromReport || summaryOnly ? report : native)?.generated_at);
  const reportSummary = getString(source?.summary) ?? (summaryOnly || undefined);

  return <section className="oracle-recorded-narrative" aria-label="Recorded Oracle market narrative">
    <h4>Oracle market narrative</h4>
    <p className="oracle-narrative-source">
      {fromReport ? "Source: Oracle report · embedded narrative."
        : source ? "Source: Oracle narrative artifact."
        : summaryOnly ? "Source: Oracle report · summary only; detailed commentary was not recorded."
        : "No recorded Oracle market narrative is available in the supplied evidence."}
      {asOf && (source || summaryOnly) ? <> Market snapshot: <time dateTime={asOf} title={asOf}>{recordedTime(asOf)}</time>.</> : null}
    </p>
    {mismatch && !fromReport ? <p role="status">The separate Oracle narrative does not match the report’s recorded identifiers and is not shown.</p> : null}
    {source ? <div className="oracle-commentary">
      {COMMENTARY.map(([key, label]) => <section key={key}>
        <h5>{label}</h5>
        <p>{getString(source[key]) ?? "No commentary recorded for this topic in the selected source."}</p>
      </section>)}
    </div> : null}
    {reportSummary ? <div className="oracle-narrative-summary"><h5>Recorded summary</h5><p>{reportSummary}</p></div> : null}
    <NarrativeWarnings documents={[report, source, !mismatch ? native : undefined]} />
    <p className="book-note">Recorded Oracle wording, not a new analysis or a streaming market update. It describes the measured fleet, not whichever symbol is open in Navigator. ModelDock commentary is separately labeled on page 4.</p>
  </section>;
}

/** The accepted model's explanation and cited statements stay distinct from Oracle authority. */
export function ModelDockNarrativeDetails({ viewModel }: { viewModel: MissionViewModel }) {
  const narrative = loaded(viewModel, "oracle_modeldock_narrative");
  if (!narrative) return <p>No recorded ModelDock narrative details are available in the supplied evidence.</p>;
  const uncertainties = getStringArray(narrative.uncertainties);
  const statements = Array.isArray(narrative.observed_facts) ? narrative.observed_facts : undefined;
  return <section className="oracle-recorded-narrative" aria-label="Recorded ModelDock narrative details">
    <p className="oracle-narrative-source">Recorded model: {viewModel.modeldock.model ?? "Not recorded"} · Provider: {viewModel.modeldock.provider ?? "Not recorded"}.
      {viewModel.modeldock.lastSuccessfulInference ? <> Inference recorded: <time dateTime={viewModel.modeldock.lastSuccessfulInference} title={viewModel.modeldock.lastSuccessfulInference}>{recordedTime(viewModel.modeldock.lastSuccessfulInference)}</time>.</> : null}
      {" "}This page does not start inference or check the model’s present availability.</p>
    <h4>Confidence and limits</h4>
    <p>{getString(narrative.confidence_explanation) ?? "No confidence explanation was recorded."}</p>
    <p className="book-note">This explanation is recorded model wording, not a calibrated probability or proof of complete coverage. Oracle’s recorded exclusions and missing inputs still apply.</p>
    <h4>Recorded model statements and their sources</h4>
    {!statements?.length ? <p>No source-linked statements are recorded in this artifact.</p> : <ol className="oracle-model-statements">
      {statements.map((value, index) => {
        const fact = getObject(value);
        const sourceName = getString(fact?.source_artifact);
        const pointer = getString(fact?.json_pointer);
        const evidence = sourceName && FACT_SOURCES.includes(sourceName)
          ? getEvidence(viewModel, sourceName as MissionEvidenceName) : undefined;
        const reference = evidence?.status === "LOADED" ? evidence.reference : undefined;
        const path = reference?.path;
        const indexed = reference && viewModel.artifactIndex.get(reference.name);
        const safe = Boolean(path && isMissionRelativePath(path) && !path.includes("\\") && !path.includes("%")
          && indexed?.path === path && indexed.sha256 === reference?.sha256);
        return <li key={index}>
          <p>{getString(fact?.statement) ?? "This recorded statement is unavailable or has an unsupported format."}</p>
          <p className="oracle-narrative-source">
            {safe && path ? <a href={missionRelativeUrl(viewModel.baseUrl, path)} target="_blank" rel="noreferrer">{sourceName}</a> : <span>Source evidence not available for linking{sourceName ? `: ${sourceName}` : "."}</span>}
            {pointer ? <> · recorded field <code>{pointer}</code></> : null}
          </p>
        </li>;
      })}
    </ol>}
    <h4>Recorded uncertainty</h4>
    {uncertainties?.length ? <ul>{uncertainties.map((item, index) => <li key={index}>{item}</li>)}</ul>
      : <p>{uncertainties ? "No uncertainty items were recorded. This is not an assessment that uncertainty is absent." : "No uncertainty list was recorded."}</p>}
    <NarrativeWarnings documents={[loaded(viewModel, "oracle_report"), narrative]} />
  </section>;
}
