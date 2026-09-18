/** Synthetic UI transport fixture only; never a product fallback or model result. */
import { ORACLE_BRIEF_SECTIONS, ORACLE_BRIEF_SOURCES, type OracleMarketBrief } from "../contracts/oracleMarketBrief";
import type { JsonObject } from "../contracts/presentation";

export function createOracleMarketBriefFixture(): OracleMarketBrief {
  const facts: OracleMarketBrief["evidence"]["facts"] = [
    { fact_id: "oracle.measurements.breadth_score", source_artifact: "oracle_measurements", json_pointer: "/breadth_score", label: "Positive participation", value: .25, meaning: "Fraction of supplied proxies with positive returns; not whole-market breadth." },
    { fact_id: "oracle.diagnostics.diagnostics_state", source_artifact: "oracle_measurement_diagnostics", json_pointer: "/diagnostics_state", label: "Diagnostics state", value: "READY", meaning: "Processing state, not market direction." },
    { fact_id: "oracle.readiness.readiness_state", source_artifact: "oracle_readiness_report", json_pointer: "/readiness_state", label: "Input readiness", value: "READY", meaning: "Input readiness is not permission to act." },
    { fact_id: "oracle.assessment.breadth_posture", source_artifact: "oracle_assessment", json_pointer: "/breadth_posture", label: "Recorded participation posture", value: "CONTRACTING_BREADTH", meaning: "Existing canonical participation classification." },
    { fact_id: "oracle.report.headline", source_artifact: "oracle_report", json_pointer: "/headline", label: "Canonical report headline", value: "Contracting breadth with mixed structure.", meaning: "Existing report wording, not a model-generated fact." },
  ];
  const source_artifacts = Object.fromEntries(ORACLE_BRIEF_SOURCES.map((name) => [name, {
    name, path: `oracle/${name}.json`, sha256: "a".repeat(64), producer: "oracle", byte_size: 128,
    schema_version: null, observed_at: "2026-09-15T23:05:20Z",
  }])) as OracleMarketBrief["evidence"]["source_artifacts"];
  const prose = [
    "Participation is uneven within the recorded proxy universe. The supplied breadth posture describes that limited snapshot, not the whole market.",
    "Concentrated absolute movement does not identify winners; losses can contribute to the same measure.",
    "The recorded group balance should be separated from temporal rotation. Earlier comparison evidence is unavailable.",
    "The supplied posture describes existing cross-sectional structure, with uncertainty about what follows.",
    "The useful review dimensions are participation, concentration and missing coverage, rather than individual symbols.",
    "Missing prior evidence limits temporal comparisons, and processing readiness does not resolve those limitations.",
  ];
  return {
    schema_version: "blackpod.oracle_market_brief.v1", brief_id: "oracle-market-brief-" + "b".repeat(64),
    evidence: { schema_version: "blackpod.oracle_market_brief_evidence.v1", evidence_id: "oracle-brief-evidence-" + "c".repeat(64),
      mission_id: "mission-live-oracle-test", request_id: "request-live-oracle-test", symbol: "AAPL", run_mode: "LIVE",
      as_of: "2026-09-15T22:00:00Z", source_artifacts, facts, warnings: ["MISSING_PRIOR_ORACLE_MEASUREMENTS"], blockers: [],
      limitations: ["Historical captured evidence, not a streaming market update.", "Semantic entailment is not automatically verified."] },
    report: { schema_version: "blackpod.oracle_market_brief_draft.v1",
      headline: { text: "Uneven participation calls for a careful reading of the recorded structure", fact_ids: [facts[0].fact_id] },
      sections: ORACLE_BRIEF_SECTIONS.map((section_id, index) => ({ section_id, paragraphs: [{ text: prose[index], fact_ids: [facts[index % facts.length].fact_id] }] })) },
    generated_at: "2026-09-16T01:01:00Z",
    provenance: { provider: "mlx", model: "synthetic-ui-model", model_revision: null, trace_id: "synthetic-ui-trace", mocked: false,
      request_sha256: "d".repeat(64), response_sha256: "e".repeat(64), started_at: "2026-09-16T01:00:00Z", observed_at: "2026-09-16T01:00:55Z", canonical_module_sha256: "f".repeat(64) },
    generation_method: "MODELDOCK_GROUNDED_SYNTHESIS", observation_only: true, order_submission_enabled: false, authoritative: false,
    validation_status: "STRUCTURE_CITATIONS_AND_GUARDRAILS_CHECKED_NOT_ENTAILMENT_VERIFIED",
  };
}

/** Minimal matching source documents for browser binding tests, not Oracle contracts. */
export function oracleMarketBriefSourceDocuments(brief: OracleMarketBrief): Record<string, JsonObject> {
  const documents: Record<string, JsonObject> = Object.fromEntries(ORACLE_BRIEF_SOURCES.map((name) => [name, {}]));
  for (const fact of brief.evidence.facts) documents[fact.source_artifact][fact.json_pointer.slice(1)] = fact.value;
  return documents;
}
