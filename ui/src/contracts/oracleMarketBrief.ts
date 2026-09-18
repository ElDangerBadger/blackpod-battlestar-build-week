import type { ArtifactReference } from "./presentation";

export const ORACLE_MARKET_BRIEF_SCHEMA = "blackpod.oracle_market_brief.v1" as const;
export const ORACLE_BRIEF_EVIDENCE_SCHEMA = "blackpod.oracle_market_brief_evidence.v1" as const;
export const ORACLE_BRIEF_DRAFT_SCHEMA = "blackpod.oracle_market_brief_draft.v1" as const;
export const ORACLE_BRIEF_SOURCES = ["oracle_measurements", "oracle_measurement_diagnostics", "oracle_readiness_report", "oracle_assessment", "oracle_report"] as const;
export type OracleBriefSource = typeof ORACLE_BRIEF_SOURCES[number];
export const ORACLE_BRIEF_SECTIONS = ["participation", "leadership", "rotation", "risk", "watchpoints", "limits"] as const;
export type OracleBriefSectionId = typeof ORACLE_BRIEF_SECTIONS[number];
export interface OracleBriefFact {
  fact_id: string; source_artifact: OracleBriefSource; json_pointer: string; label: string; value: string | number | boolean | string[]; meaning: string;
}
export interface OracleBriefParagraph { text: string; fact_ids: string[] }
export interface OracleMarketBrief {
  schema_version: typeof ORACLE_MARKET_BRIEF_SCHEMA;
  brief_id: string;
  evidence: {
    schema_version: typeof ORACLE_BRIEF_EVIDENCE_SCHEMA; evidence_id: string;
    mission_id: string; request_id: string; symbol: string; run_mode: "LIVE"; as_of: string;
    source_artifacts: Record<OracleBriefSource, ArtifactReference>; facts: OracleBriefFact[];
    warnings: string[]; blockers: string[]; limitations: string[];
  };
  report: {
    schema_version: typeof ORACLE_BRIEF_DRAFT_SCHEMA;
    headline: OracleBriefParagraph;
    sections: { section_id: OracleBriefSectionId; paragraphs: OracleBriefParagraph[] }[];
  };
  generated_at: string;
  provenance: {
    provider: "mlx"; model: string; model_revision: string | null; trace_id: string; mocked: false;
    request_sha256: string; response_sha256: string; started_at: string; observed_at: string; canonical_module_sha256: string;
  };
  generation_method: "MODELDOCK_GROUNDED_SYNTHESIS";
  observation_only: true; order_submission_enabled: false; authoritative: false;
  validation_status: "STRUCTURE_CITATIONS_AND_GUARDRAILS_CHECKED_NOT_ENTAILMENT_VERIFIED";
}
