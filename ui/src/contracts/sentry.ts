/** Read-only copies of canonical microcap_sentry.snapshot.v1 records, not Cabin scores. */
export const SENTRY_CLASSIFICATIONS = [
  "INELIGIBLE", "DORMANT", "POWDER_KEG", "WATCH", "CATALYST_DETECTED", "IGNITION",
  "BREAKOUT_DEVELOPING", "CONFIRMED_MOMENTUM", "EXTENDED", "DILUTION_RISK", "FAILED_EVENT", "HALTED", "INSUFFICIENT_DATA",
] as const;
export type SentryClassification = typeof SENTRY_CLASSIFICATIONS[number];
export interface SentryFactorContribution {
  factor: string;
  contribution: number;
  observed_value: number | boolean | string | null;
  threshold: number | boolean | string | null;
  /** Older canonical archives predate this field. Absence must not become a computed weight. */
  configured_weight?: number | null;
  reason: string;
}
export interface SentryScore {
  total_score: number;
  contributions: SentryFactorContribution[];
  reasons: string[];
  warnings: string[];
  missing_data_fields: string[];
}
export interface SentryContinuation extends Omit<SentryScore, "total_score"> { total_score: number | null }
export interface SentryEligibility { eligible: boolean; reasons: string[]; warnings: string[]; missing_fields: string[] }
export interface SentryFeatures {
  price_change_1m_pct: number | null;
  price_change_5m_pct: number | null;
  price_change_15m_pct: number | null;
  distance_from_session_high_pct: number | null;
  distance_from_vwap_pct: number | null;
  new_session_high: boolean | null;
  volume_ratio_1m: number | null;
  volume_ratio_5m: number | null;
  volume_acceleration: number | null;
  cumulative_relative_volume: number | null;
  spread_pct: number | null;
  dollar_volume: number | null;
  quote_imbalance: number | null;
  executable_liquidity_warning: boolean;
  warnings: string[];
  missing_data_fields: string[];
}
export interface SentrySymbolProfile {
  symbol: string; exchange: string | null; price: number | null; market_cap: number | null;
  float_shares: number | null; average_daily_dollar_volume: number | null;
  short_interest_pct: number | null; days_to_cover: number | null;
  volatility_compression: number | boolean | null; breakout_proximity_pct: number | null;
  recent_material_filing: boolean | null; prior_spike_count: number | null;
  active_shelf: boolean | null; warrant_overhang: boolean | null; recent_reverse_split: boolean | null;
}
export interface SentryCatalyst {
  symbol: string; timestamp: string; catalyst_type: "NEWS" | "SEC_FILING" | "TRADING_HALT" | "OTHER";
  summary: string; material: boolean | null; source_event_id: string | null; confidence: number | null;
}
export interface SentryNewsEvent {
  event_id: string; symbol: string; timestamp: string; headline: string; summary: string;
  source: string; material: boolean | null;
}
export interface SentryFilingEvent {
  event_id: string; symbol: string; timestamp: string; form_type: string; summary: string;
  accession_number: string | null; material: boolean | null; is_new: boolean | null;
  dilution_risk: boolean | null; active_shelf: boolean | null; warrant_overhang: boolean | null;
  reverse_split: boolean | null;
}
export interface SentryHaltEvent {
  event_id: string; symbol: string; timestamp: string; active: boolean; reason: string;
  halt_code: string | null; resumed_at: string | null;
}
export interface SentrySnapshot {
  schema_version: "microcap_sentry.snapshot.v1";
  event_id: string; observed_at: string; symbol: string; classification: SentryClassification;
  eligibility: SentryEligibility; features: SentryFeatures; powder_keg: SentryScore; ignition: SentryScore;
  symbol_profile: SentrySymbolProfile | null; continuation: SentryContinuation | null;
  catalysts: SentryCatalyst[]; news_events: SentryNewsEvent[];
  filing_events: SentryFilingEvent[]; halt_events: SentryHaltEvent[];
  risks: string[]; missing_information: string[]; reasons: string[];
  observation_only: true; order_submission_enabled: false;
}
export interface SentrySource {
  label: string; kind: "RESEARCH" | "RECORDED"; file_name: string; sha256: string;
  byte_size: number; latest_observed_at: string | null; raw_count: number; duplicate_count: number;
}
export interface SentryFeed {
  schema_version: "blackpod.sentry_feed.v1";
  status: "READY" | "NOT_CONFIGURED" | "UNAVAILABLE";
  checked_at: string; message: string; source: SentrySource | null; observations: SentrySnapshot[];
}
