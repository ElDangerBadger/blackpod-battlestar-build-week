import { SENTRY_RESEARCH_ARMS, type SentryResearchFeed } from "../contracts/sentryResearch";

/** Synthetic transport fixture, never imported by production UI or used as fallback. */
export function createSentryResearchFixture(): SentryResearchFeed {
  const cohort = "AAPL AMD AMZN COST GOOGL JPM META MSFT NVDA TSLA UNH XOM DIA IWD IWF IWM MTUM QQQ QUAL SPY USMV XLB XLC XLE XLF XLI XLK XLP XLRE XLU XLV XLY ABT ADP CAT CSCO DE DIS KO LOW MU PEP RTX WMT AGG BND EEM EFA GLD IAU IEF LQD SLV TLT USO XBI".split(" ").sort();
  return {
    schema_version: "blackpod.sentry_research_feed.v1", status: "READY", checked_at: "2026-09-18T05:00:00Z", message: "Fixed research checkpoint read.",
    source: { label: "Sentry Calibration V2 checkpoint", kind: "FIXED_RESEARCH_CHECKPOINT", archive_as_of: "2026-09-18T04:40:00Z",
      files: ["development-summary.json", "warmup-summary.json", "protocol-summary.json", "review-summary.json"].map((file_name) => ({ file_name, sha256: "a".repeat(64), byte_size: 2000 })),
      declared_upstream_hashes: { cache: "b".repeat(64), results: "c".repeat(64) }, upstream_artifacts_reverified: false },
    study: { development_id: "development-test", scope: "HISTORICAL_DEVELOPMENT", training_period: { start: "2019-01-01", end: "2022-12-31" },
      development_period: { start: "2023-01-01", end: "2024-12-31" }, session_count: 502, cohort, windows: [20, 60], primary_arm: "ELIGIBLE_INCUMBENT_FIRST",
      profile_statuses: { GENERAL_EQUITY: "RESEARCH_ONLY", ETF: "RESEARCH_ONLY" }, criteria: { mean_new_names_limit: 2, minimum_mean_jaccard: 2 / 3, capacity: 6, per_profile_capacity: 4 },
      all_policies_failed: true, policies: SENTRY_RESEARCH_ARMS.map((arm, index) => ({ arm, role: (["CONTROL", "PRIMARY", "EXPLORATORY"] as const)[index],
        windows: ([20, 60] as const).map((lookback, i) => ({ lookback, new_names_total: [[1669, 1456], [1422, 1308], [931, 884]][index][i],
          mean_new_names_per_day: [[1669 / 502, 1456 / 502], [1422 / 502, 1308 / 502], [931 / 502, 884 / 502]][index][i], sessions: 502,
          mean_selected: 4.9, eligible_coverage: .56, top_symbols: cohort.slice(0, 6).map((symbol, rank) => ({ symbol, selected_sessions: 100 - rank })) })),
        mean_overlap: [.536419, .513449, .525723][index], meets_overlap: false, meets_churn: index === 2, capped_by_construction: index === 2 })) },
    prospective: { manifest_id: "sentry-prospective-protocol-test", period: { start: "2026-09-18", end: "2026-12-11" }, planned_sessions: 60, completed_sessions: 0,
      status: "BLOCKED_MISSING_REQUIRED_EVIDENCE", warmup: { session: "2026-09-17", status: "FAILED_CLOSED_NOT_A_VALID_WARMUP", expected_symbols: 56,
        ready_symbols: 23, failed_symbols: 1, blocked_symbols: 32, complete_cohort_sealed: false, failure_evidence_sealed: true, provider_requests: 24,
        conflict: { symbol: "IWM", session: "2026-09-16", fields: ["volume"], prior_volume: "40000000", incoming_volume: "40000001" },
        first_captured_at: "2026-09-18T04:15:00Z", last_captured_at: "2026-09-18T04:30:00Z" }, calendar_blocker_dates: ["2026-11-27"], scheduler_loaded_at_archive: true },
    limitations: ["Historical current metadata does not establish point-in-time size.", "No independent lifecycle accuracy labels."],
    observation_only: true, order_submission_enabled: false, current_attention_published: false,
  };
}
