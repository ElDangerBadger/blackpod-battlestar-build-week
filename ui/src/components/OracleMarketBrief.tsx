import { useId } from "react";
import type { OracleBriefFact, OracleBriefParagraph, OracleBriefSectionId, OracleMarketBrief as Brief } from "../contracts/oracleMarketBrief";
import type { ArtifactReference } from "../contracts/presentation";
import { missionRelativeUrl, type MissionEvidenceName } from "../data/loadMission";
import { isMissionRelativePath } from "../data/validate";
import { getEvidence, type MissionViewModel } from "../data/viewModel";
import "./oracle-market-brief.css";

const TITLES: Record<OracleBriefSectionId, string> = {
  participation: "Participation",
  leadership: "Leadership",
  rotation: "Sector balance",
  risk: "Risk posture",
  watchpoints: "What to watch",
  limits: "Limits to this reading",
};
const OVERVIEW_SECTIONS = new Set<OracleBriefSectionId>(["participation", "leadership", "rotation", "risk"]);
const REFERENCE_FIELDS = ["name", "path", "sha256", "producer", "byte_size", "schema_version", "observed_at"] as const;
const recordedTime = (value: string) => new Intl.DateTimeFormat("en-US", {
  year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: "UTC", timeZoneName: "short",
}).format(new Date(value));

function sameReference(a: ArtifactReference | null | undefined, b: ArtifactReference): boolean {
  return Boolean(a && REFERENCE_FIELDS.every((key) => a[key] === b[key]));
}

/** Only existing loaded and indexed mission artifacts are eligible for links. */
function sourceUrl(fact: OracleBriefFact, brief: Brief, model: MissionViewModel): string | null {
  const reference = brief.evidence.source_artifacts[fact.source_artifact];
  const evidence = getEvidence(model, fact.source_artifact as MissionEvidenceName);
  if (evidence?.status !== "LOADED" || !sameReference(evidence.reference, reference)
    || !sameReference(model.artifactIndex.get(fact.source_artifact), reference)
    || !isMissionRelativePath(reference.path) || /[%?#\x00-\x1f\x7f]/.test(reference.path)) return null;
  return missionRelativeUrl(model.baseUrl, reference.path);
}

export function OracleMarketBrief({ brief, viewModel }: { brief: Brief; viewModel: MissionViewModel }) {
  const id = useId();
  const facts = new Map(brief.evidence.facts.map((fact) => [fact.fact_id, fact]));
  const link = (fact: OracleBriefFact) => {
    const url = sourceUrl(fact, brief, viewModel);
    return url ? <a href={url} target="_blank" rel="noreferrer" title={`${fact.source_artifact} · ${fact.json_pointer}`}>{fact.label}</a>
      : <span>{fact.label} · source link unavailable</span>;
  };
  const citations = (paragraph: OracleBriefParagraph) => <ul className="market-brief-citations" aria-label="Cited recorded facts">
    {paragraph.fact_ids.map((factId) => {
      const fact = facts.get(factId);
      return <li key={factId}>{fact ? link(fact) : "Cited fact unavailable"}</li>;
    })}
  </ul>;
  return <section className="oracle-market-brief" aria-label="Oracle’s market brief">
    <header>
      <h4 className="market-brief-headline">{brief.report.headline.text}</h4>
      <p className="market-brief-context">ModelDock interpretation · Snapshot <time dateTime={brief.evidence.as_of} title={brief.evidence.as_of}>{recordedTime(brief.evidence.as_of)}</time> · Not a live update or trading permission.</p>
    </header>
    {/* Verbatim accepted paragraphs in their recorded order, not browser synthesis. */}
    <div className="market-brief-overview" role="region" aria-label="Recorded market overview">
      {brief.report.sections.filter((section) => OVERVIEW_SECTIONS.has(section.section_id)).map((section) =>
        <div key={section.section_id} data-overview-section={section.section_id}>
          {section.paragraphs.map((paragraph, index) => <p key={index}>{paragraph.text}</p>)}
        </div>)}
    </div>
    {brief.report.sections.filter((section) => !OVERVIEW_SECTIONS.has(section.section_id)).map((section) => <section className="market-brief-section" key={section.section_id} aria-labelledby={`${id}-${section.section_id}`}>
      <h5 id={`${id}-${section.section_id}`}>{TITLES[section.section_id]}</h5>
      {section.paragraphs.map((paragraph, index) => <p key={index}>{paragraph.text}</p>)}
    </section>)}
    {brief.evidence.warnings.length || brief.evidence.blockers.length ? <aside aria-label="Canonical brief warnings and blockers">
      <h5>Recorded coverage and caveats</h5>
      {brief.evidence.warnings.length ? <><p>Canonical warnings</p><ul className="market-brief-recorded-limits">{brief.evidence.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></> : null}
      {brief.evidence.blockers.length ? <><p>Canonical blockers</p><ul className="market-brief-recorded-limits">{brief.evidence.blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}</ul></> : null}
    </aside> : null}
    <details>
      <summary>Sources for this reading</summary>
      <h5>Headline</h5>
      {citations(brief.report.headline)}
      {brief.report.sections.map((section) => <div key={section.section_id}>
        <h5>{TITLES[section.section_id]}</h5>
        {section.paragraphs.map((paragraph, index) => <div key={index}>
          <p>Paragraph {index + 1}</p>{citations(paragraph)}
        </div>)}
      </div>)}
    </details>
    <details>
      <summary>Evidence behind this brief · {facts.size} recorded facts</summary>
      <p>Exact supplied values and their canonical meanings—not fresh browser calculations. A citation identifies evidence; it does not independently prove the model’s interpretation.</p>
      <ol className="market-brief-facts">{brief.evidence.facts.map((fact) => <li key={fact.fact_id}>
        <strong>{fact.label}</strong><p>{fact.meaning}</p>
        <pre aria-label={`Recorded value: ${fact.label}`}>{JSON.stringify(fact.value, null, 2)}</pre>
        <p>{link(fact)} · <code>{fact.json_pointer}</code></p><p>Fact ID: <code>{fact.fact_id}</code></p>
      </li>)}</ol>
    </details>
    <details>
      <summary>Model provenance and limits</summary>
      <p className="market-brief-boundary">Supplemental model commentary—not authoritative Oracle analysis, a current market update, or permission to act. Structure, citations, and guardrails were checked; that does not verify that every interpretation follows from its sources. Canonical measurements remain authoritative.</p>
      <dl className="market-brief-clock">
        <div><dt>Brief generated</dt><dd><time dateTime={brief.generated_at} title={brief.generated_at}>{recordedTime(brief.generated_at)}</time></dd></div>
      </dl>
      <p>Recorded real ModelDock inference. Opening this page does not call the model, fetch prices, or verify the model’s present availability. This report concerns its supplied proxy universe, not a selected Navigator symbol.</p>
      <dl className="market-brief-provenance">
        <dt>Provider</dt><dd>{brief.provenance.provider}</dd><dt>Model</dt><dd>{brief.provenance.model}</dd>
        <dt>Model revision</dt><dd>{brief.provenance.model_revision ?? "Not recorded"}</dd><dt>Trace</dt><dd><code>{brief.provenance.trace_id}</code></dd>
        <dt>Inference started</dt><dd>{recordedTime(brief.provenance.started_at)}</dd><dt>Response recorded</dt><dd>{recordedTime(brief.provenance.observed_at)}</dd>
        <dt>Request SHA-256</dt><dd><code>{brief.provenance.request_sha256}</code></dd><dt>Response SHA-256</dt><dd><code>{brief.provenance.response_sha256}</code></dd>
        <dt>Canonical module SHA-256</dt><dd><code>{brief.provenance.canonical_module_sha256}</code></dd>
        <dt>Brief identity</dt><dd><code>{brief.brief_id}</code></dd><dt>Evidence identity</dt><dd><code>{brief.evidence.evidence_id}</code></dd>
      </dl>
      <ul className="market-brief-recorded-limits">{brief.evidence.limitations.map((value) => <li key={value}>{value}</li>)}</ul>
      <p>No trading authority, approvals, orders, or downstream instructions are created by this commentary.</p>
    </details>
  </section>;
}
