/** Presentation of one explicitly selected, offline-verified experiment. */
export interface ShadowSession { date: string; open_at: string; close_at: string; session_open_at: string; session_close_at: string }
export interface ShadowEvidence { path: string; sha256: string; size_bytes: number }
export interface ShadowProtocol {
  schema_version: "blackpod.shadow_experiment_protocol.v1";
  method_version: string;
  experiment_id: string;
  frozen_at: string;
  first_signal_session: string;
  universe: ["QQQ", "SPY"];
  sessions: ShadowSession[];
  context_sessions: ShadowSession[];
  hypothesis_evidence: ShadowEvidence;
  calendar_evidence: ShadowEvidence;
  calendar_receipt_evidence: ShadowEvidence;
  calendar_captured_at: string;
  original_hypothesis_id: string;
  original_horizon: Record<string, string | number>;
  observation_basis: string;
  availability_buffer_seconds: number;
  criteria: Record<string, string | number>;
  scope: "PROSPECTIVE_OBSERVATION_ONLY";
  auto_trading_enabled: false;
  authority: Record<string, false>;
  execution_status: "NOT_EXECUTED";
  realized_trade_pnl: null;
  limitations: string[];
}

export interface ShadowPrediction {
  prediction_id: string;
  symbol: "QQQ" | "SPY";
  signal_session: string;
  signal_close_at: string;
  signal_available_at: string;
  entry_session: string;
  entry_open_at: string;
  exit_session: string;
  exit_open_at: string;
  outcome_available_at: string;
  recorded_at: string;
  status: string;
  reason_codes: string[];
  signal_return: string | null;
  signal_close: string | null;
  previous_close: string | null;
}

export interface ShadowOutcome {
  outcome_id: string;
  prediction_id: string;
  symbol: "QQQ" | "SPY";
  recorded_at: string;
  status: string;
  candidate_gross_return: string | null;
  control_gross_return: string | null;
  cash_return: string | null;
  excess_over_control: string | null;
  reason_codes: string[];
  entry_price: string | null;
  exit_price: string | null;
}

export interface ShadowExperimentView {
  schema_version: "blackpod.shadow_experiment_view.v1";
  protocol: ShadowProtocol;
  journal: { event_count: number; evidence_blob_count: number; last_entry_sha256: string };
  predictions: ShadowPrediction[];
  outcomes: ShadowOutcome[];
  summary: {
    opportunity_count: number;
    recorded_prediction_count: number;
    pending_prediction_count: number;
    candidate_count: number;
    abstention_count: number;
    missed_count: number;
    missing_input_count: number;
    observed_outcome_count: number;
    pending_outcome_count: number;
    mean_gross_return: string | null;
    mean_gross_excess_over_control: string | null;
    positive_gross_outcome_fraction: string | null;
    conclusion: string;
    economic_support: "NOT_EVALUABLE";
    net_return: null;
    next_action: "MANUAL_REVIEW_AFTER_PILOT_NO_AUTOMATIC_EXTENSION";
  };
  latest_captured_at: string | null;
  auto_trading_enabled: false;
  authority: Record<string, false>;
  limitations: string[];
}

export interface ShadowExperimentFeed {
  schema_version: "blackpod.shadow_experiment_feed.v1";
  checked_at: string;
  status: "READY" | "NOT_CONFIGURED" | "UNAVAILABLE";
  message: string;
  experiment: ShadowExperimentView | null;
}
