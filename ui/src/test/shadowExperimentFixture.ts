import type { ShadowExperimentFeed, ShadowSession } from "../contracts/shadowExperiment";

/** Authored presentation fixture only; never imported by the production view. */
export function createShadowExperimentFixture(withRows = false): ShadowExperimentFeed {
  const context: ShadowSession[] = [], start = new Date("2026-10-13T00:00:00Z");
  while (context.length < 33) {
    if (start.getUTCDay() !== 0 && start.getUTCDay() !== 6) {
      const date = start.toISOString().slice(0, 10);
      context.push({ date, open_at: `${date}T13:30:00Z`, close_at: `${date}T20:00:00Z`, session_open_at: `${date}T08:00:00Z`, session_close_at: `${date}T23:00:00Z` });
    }
    start.setUTCDate(start.getUTCDate() + 1);
  }
  const authority = { authorization_enabled: false, capital_activation_enabled: false, execution_enabled: false, policy_changes_enabled: false } as const;
  const reference = (path: string) => ({ path, sha256: "a".repeat(64), size_bytes: 2000 });
  const feed: ShadowExperimentFeed = {
    schema_version: "blackpod.shadow_experiment_feed.v1", checked_at: "2026-10-21T05:00:00Z", status: "READY", message: "Synthetic presentation fixture.",
    experiment: {
      schema_version: "blackpod.shadow_experiment_view.v1",
      protocol: {
        schema_version: "blackpod.shadow_experiment_protocol.v1", method_version: "blackpod.prospective_reversal_gross_proxy.v1",
        experiment_id: "synthetic-shadow-experiment", frozen_at: "2026-10-14T18:00:00Z", first_signal_session: context[1].date,
        universe: ["QQQ", "SPY"], sessions: context.slice(1, 31), context_sessions: context,
        hypothesis_evidence: reference("shadow-experiment/hypothesis.json"), calendar_evidence: reference("shadow-experiment/protocol-calendar.json"), calendar_receipt_evidence: reference("shadow-experiment/protocol-calendar-receipt.json"),
        calendar_captured_at: "2026-10-14T17:59:00Z", original_hypothesis_id: "previous-session-reversal-v1",
        original_horizon: { kind: "SWING", holding_sessions: 1, label_horizon_sessions: 1, entry_clock: "NEXT_SESSION_OPEN_AFTER_INPUT_AVAILABILITY", exit_clock: "SESSION_OPEN_AFTER_DECLARED_HOLDING_SESSIONS", overlap_policy: "NO_OVERLAPPING_POSITIONS_OR_REENTRY_WHILE_OPEN" },
        observation_basis: "PROVIDER_DAILY_BAR_OPEN_TO_OPEN_GROSS_PROXY", availability_buffer_seconds: 900,
        criteria: { signal_sessions: 30, opportunity_count: 60, minimum_observed_candidates: 12, candidate_rule: "COMPLETED_PROVIDER_CLOSE_OVER_PRIOR_CLOSE_MINUS_ONE_LT_ZERO", holding_sessions: 1, overlap_policy: "NO_OVERLAPPING_CANDIDATE_PER_SYMBOL", cash_benchmark: "ZERO_RETURN_NO_INTEREST_ASSUMED", control_benchmark: "EQUAL_WEIGHT_QQQ_SPY_SAME_PROVIDER_OPEN_DATES_UNIT_GROSS_EXPOSURE", positive_descriptive_rule: "MEAN_GROSS_RETURN_AND_MEAN_GROSS_EXCESS_OVER_CONTROL_STRICTLY_POSITIVE", sample_unit: "SYMBOL_SESSION_NOT_INDEPENDENT_OBSERVATIONS", inference: "DESCRIPTIVE_ONLY_NO_SIGNIFICANCE_OR_ECONOMIC_EDGE_CLAIM", cost_policy: "UNKNOWN_NET_METRICS_UNAVAILABLE", parameter_changes: "NO_CHANGES_WITHIN_RUN_NEW_PROTOCOL_REQUIRED", admission_deadline_seconds_before_source_session_open: 300, proxy_clock_basis: "DECLARED_EXTENDED_SESSION_OPEN_LOWER_BOUND_NOT_ACTUAL_FIRST_TRADE_TIME", source_completion: "EXTENDED_SESSION_CLOSE_PLUS_900_SECONDS", arithmetic: "DECIMAL_60_SIGNIFICANT_DIGITS_ROUND_HALF_EVEN_EXACT_PRICE_COMPARISON_FOR_SIGNAL" },
        scope: "PROSPECTIVE_OBSERVATION_ONLY", auto_trading_enabled: false, authority, execution_status: "NOT_EXECUTED", realized_trade_pnl: null, limitations: ["SYNTHETIC_FIXTURE_ONLY"],
      },
      journal: { event_count: 1, evidence_blob_count: 12, last_entry_sha256: "b".repeat(64) }, predictions: [], outcomes: [],
      summary: { opportunity_count: 60, recorded_prediction_count: 0, pending_prediction_count: 60, candidate_count: 0, abstention_count: 0, missed_count: 0, missing_input_count: 0, observed_outcome_count: 0, pending_outcome_count: 0, mean_gross_return: null, mean_gross_excess_over_control: null, positive_gross_outcome_fraction: null, conclusion: "PENDING", economic_support: "NOT_EVALUABLE", net_return: null, next_action: "MANUAL_REVIEW_AFTER_PILOT_NO_AUTOMATIC_EXTENSION" },
      latest_captured_at: null, auto_trading_enabled: false, authority, limitations: ["SYNTHETIC_PRESENTATION_FIXTURE_NOT_MARKET_EVIDENCE"],
    },
  };
  if (withRows) {
    const view = feed.experiment!;
    view.predictions = (["QQQ", "SPY"] as const).map((symbol, index) => ({
      prediction_id: `shadow-prediction-${symbol.toLowerCase()}`, symbol, signal_session: context[1].date, signal_close_at: context[1].close_at,
      signal_available_at: `${context[1].date}T23:15:00Z`, entry_session: context[2].date, entry_open_at: context[2].open_at,
      exit_session: context[3].date, exit_open_at: context[3].open_at, outcome_available_at: `${context[3].date}T23:15:00Z`,
      recorded_at: "2026-10-15T05:00:00Z", status: index === 0 ? "OBSERVATIONAL_CANDIDATE" : "ABSTAIN_NONNEGATIVE_RETURN",
      reason_codes: [index === 0 ? "NEGATIVE_COMPLETED_PROVIDER_CLOSE_RETURN" : "FROZEN_NEGATIVE_CLOSE_CONDITION_NOT_MET"],
      signal_return: index === 0 ? "-0.01" : "0.02", signal_close: index === 0 ? "99" : "102", previous_close: "100",
    }));
    view.outcomes = view.predictions.map((prediction, index) => ({
      outcome_id: `shadow-outcome-${prediction.symbol.toLowerCase()}`, prediction_id: prediction.prediction_id, symbol: prediction.symbol,
      recorded_at: "2026-10-20T05:00:00Z", status: index === 0 ? "OBSERVED_GROSS_PROXY_ONLY" : "NOT_APPLICABLE_ABSTENTION",
      candidate_gross_return: index === 0 ? "0.01" : null, control_gross_return: index === 0 ? "0.005" : null, cash_return: index === 0 ? "0" : null,
      excess_over_control: index === 0 ? "0.005" : null, reason_codes: ["SYNTHETIC_OUTCOME"], entry_price: index === 0 ? "100" : null, exit_price: index === 0 ? "101" : null,
    }));
    Object.assign(view.summary, { recorded_prediction_count: 2, pending_prediction_count: 58, candidate_count: 1, abstention_count: 1, observed_outcome_count: 1,
      mean_gross_return: "0.01", mean_gross_excess_over_control: "0.005", positive_gross_outcome_fraction: "1" });
    view.latest_captured_at = "2026-10-20T05:00:00Z";
  }
  return feed;
}
