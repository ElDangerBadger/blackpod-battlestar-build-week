import type { SentryScanEntry, SentryScanFeed, SentryScanProfile } from "../contracts/sentryScan";

/** Synthetic transport fixture only; never imported by the production UI. */
export function createSentryScanFixture(): SentryScanFeed {
  const entry = (symbol: string, selected: boolean): SentryScanEntry => ({ symbol, profile: symbol === "SPY" ? "ETF" : "GENERAL_EQUITY",
    percentile: selected ? .98 : null, metric_name: selected ? "range_expansion" : null, sensor_result_id: `sensor-${symbol}`,
    winning_assessment_id: selected ? `assessment-${symbol}` : null, calibration_id: selected ? "calibration-test" : null,
    reasons: [selected ? "SELECTED" : "NO_ELIGIBLE_ASSESSMENT"], quality_flags: [] });
  return { schema_version: "blackpod.sentry_scan_feed.v1", checked_at: "2026-09-18T07:00:00Z", status: "READY", message: "Saved offline scan receipt.",
    observation_only: true, order_submission_enabled: false, current_attention_published: false,
    source: { file_name: "scan.json", sha256: "a".repeat(64), byte_size: 5000, declared_evidence_reverified: false },
    scan: { scan_id: "scan-test", scan_kind: "OFFLINE_RESEARCH_SNAPSHOT", session_date: "2026-09-17", as_of: "2026-09-18T06:00:00+00:00",
      manifest_sha256: "b".repeat(64), reference_manifest_id: "references-test", validation_protocol_id: "protocol-test", calibration_ids: ["calibration-test"],
      configuration: { windows: [20, 60], minimum_history_sessions: 66, capacity: 6, minimum_percentile: .95, per_profile_capacity: { GENERAL_EQUITY: 4, ETF: 4 } },
      population: { requested: ["AAPL", "IWM", "SPY"], observed: ["AAPL", "SPY"], failed: ["IWM"], requested_count: 3, observed_count: 2, failed_count: 1 },
      symbols: ["AAPL", "IWM", "SPY"].map((symbol) => symbol === "IWM" ? { symbol, status: "EXCLUDED" as const, profile: "ETF" as const, reasons: ["SOURCE_CAPTURE_FAILED"], history: null,
        failure_evidence: { file_name: "IWM-failure.json", sha256: "c".repeat(64), byte_size: 1000, receipt_id: "failure-IWM", status: "CONFLICT" }, history_validation: null } : {
        symbol, status: "OBSERVED" as const, profile: (symbol === "SPY" ? "ETF" : "GENERAL_EQUITY") as SentryScanProfile, reasons: [],
        history: { file_name: `${symbol}.csv`, sha256: "d".repeat(64), byte_size: 3000, provider: "YAHOO", captured_at: "2026-09-18T05:00:00Z", source_receipt_id: `history-${symbol}`, first_session: "2026-01-02", last_session: "2026-09-17", row_count: 178 },
        failure_evidence: null, history_validation: { report_id: `validation-${symbol}`, structurally_valid: true, research_usable: true, errors: [], warnings: ["CURRENT_ONLY_METADATA"] } }),
      windows: ([20, 60] as const).map((lookback) => ({ lookback, selection_id: `selection-${lookback}`, policy_id: "policy-test", candidate_count: 2, eligible_candidate_count: 1, capacity_remaining: 5,
        selected: [entry(lookback === 20 ? "AAPL" : "SPY", true)], excluded: [entry(lookback === 20 ? "SPY" : "AAPL", false)] })),
      profile_statuses: { GENERAL_EQUITY: "RESEARCH_ONLY", ETF: "RESEARCH_ONLY" }, limitations: ["Current metadata does not establish historical market-cap eligibility."] },
  };
}
