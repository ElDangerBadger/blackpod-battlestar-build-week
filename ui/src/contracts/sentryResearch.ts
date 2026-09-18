/** Supplied archival summaries only. No Cabin scoring, scanning or symbol actions. */
export const SENTRY_RESEARCH_ARMS = ["BASELINE", "ELIGIBLE_INCUMBENT_FIRST", "ELIGIBLE_INCUMBENT_FIRST_MAX_2_NEW"] as const;
export type SentryResearchArm = typeof SENTRY_RESEARCH_ARMS[number];
export interface SentryResearchWindow {
  lookback: 20 | 60; mean_new_names_per_day: number; new_names_total: number; sessions: number;
  mean_selected: number; eligible_coverage: number;
  top_symbols: { symbol: string; selected_sessions: number }[];
}
export interface SentryResearchPolicy {
  arm: SentryResearchArm; role: "CONTROL" | "PRIMARY" | "EXPLORATORY";
  windows: SentryResearchWindow[]; mean_overlap: number; meets_overlap: boolean; meets_churn: boolean;
  capped_by_construction: boolean;
}
export interface SentryResearchStudy {
  development_id: string; scope: string; training_period: { start: string; end: string };
  development_period: { start: string; end: string }; session_count: number; cohort: string[];
  windows: number[]; primary_arm: "ELIGIBLE_INCUMBENT_FIRST";
  profile_statuses: { GENERAL_EQUITY: "RESEARCH_ONLY"; ETF: "RESEARCH_ONLY" };
  criteria: { mean_new_names_limit: number; minimum_mean_jaccard: number; capacity: number; per_profile_capacity: number };
  all_policies_failed: boolean; policies: SentryResearchPolicy[];
}
export interface SentryResearchProspective {
  manifest_id: string; period: { start: string; end: string }; planned_sessions: number;
  completed_sessions: number; status: string;
  warmup: { session: string; status: string; expected_symbols: number; ready_symbols: number;
    failed_symbols: number; blocked_symbols: number; complete_cohort_sealed: boolean;
    failure_evidence_sealed: boolean; provider_requests: number;
    conflict: { symbol: string; session: string; fields: string[]; prior_volume: string; incoming_volume: string };
    first_captured_at: string; last_captured_at: string };
  calendar_blocker_dates: string[]; scheduler_loaded_at_archive: boolean;
}
export interface SentryResearchFeed {
  schema_version: "blackpod.sentry_research_feed.v1"; checked_at: string;
  status: "READY" | "UNAVAILABLE" | "NOT_CONFIGURED"; message: string;
  source: null | { label: string; kind: "FIXED_RESEARCH_CHECKPOINT"; archive_as_of: string;
    files: { file_name: string; sha256: string; byte_size: number }[];
    declared_upstream_hashes: { cache: string; results: string }; upstream_artifacts_reverified: false };
  study: SentryResearchStudy | null; prospective: SentryResearchProspective | null; limitations: string[];
  observation_only: true; order_submission_enabled: false; current_attention_published: false;
}
