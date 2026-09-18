/** Supplied offline scan receipt only; never an executable scan request. */
export type SentryScanProfile = "GENERAL_EQUITY" | "ETF";
export interface SentryScanFile { file_name: string; sha256: string; byte_size: number }
export interface SentryScanEntry {
  symbol: string; profile: SentryScanProfile; percentile: number | null; metric_name: string | null;
  sensor_result_id: string; winning_assessment_id: string | null; calibration_id: string | null;
  reasons: string[]; quality_flags: string[];
}
export interface SentryScanWindow {
  lookback: 20 | 60; selection_id: string; policy_id: string; candidate_count: number;
  eligible_candidate_count: number; capacity_remaining: number;
  selected: SentryScanEntry[]; excluded: SentryScanEntry[];
}
export interface SentryScanSymbol {
  symbol: string; status: "OBSERVED" | "EXCLUDED"; reasons: string[]; profile: SentryScanProfile | null;
  history: null | (SentryScanFile & { provider: string; captured_at: string; source_receipt_id: string;
    first_session: string | null; last_session: string | null; row_count: number });
  failure_evidence: null | (SentryScanFile & { receipt_id: string; status: string });
  history_validation: null | { report_id: string; structurally_valid: boolean; research_usable: boolean; errors: string[]; warnings: string[] };
}
export interface SentryScan {
  scan_id: string; scan_kind: "OFFLINE_RESEARCH_SNAPSHOT"; session_date: string; as_of: string;
  manifest_sha256: string; reference_manifest_id: string; validation_protocol_id: string; calibration_ids: string[];
  configuration: { windows: [20, 60]; minimum_history_sessions: 66; capacity: number; minimum_percentile: number; per_profile_capacity: Record<SentryScanProfile, number> };
  population: { requested: string[]; observed: string[]; failed: string[]; requested_count: number; observed_count: number; failed_count: number };
  symbols: SentryScanSymbol[]; windows: SentryScanWindow[];
  profile_statuses: Record<SentryScanProfile, "RESEARCH_ONLY">; limitations: string[];
}
export interface SentryScanFeed {
  schema_version: "blackpod.sentry_scan_feed.v1"; checked_at: string;
  status: "READY" | "UNAVAILABLE" | "NOT_CONFIGURED"; message: string;
  source: null | (SentryScanFile & { declared_evidence_reverified: false }); scan: SentryScan | null;
  observation_only: true; order_submission_enabled: false; current_attention_published: false;
}
