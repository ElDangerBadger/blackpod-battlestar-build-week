import type { ShadowExperimentFeed } from "../contracts/shadowExperiment";

export const SHADOW_EXPERIMENT_URL = "/live/shadow-experiment/current.json";
export const SHADOW_EXPERIMENT_MAX_BYTES = 512 * 1024;
const invalid = (): never => { throw new Error("Shadow experiment view is unavailable or invalid."); };
function object(value: unknown, keys?: readonly string[]): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return invalid();
  const result = value as Record<string, unknown>;
  if (keys && (Object.keys(result).length !== keys.length || keys.some((key) => !Object.hasOwn(result, key)))) invalid();
  return result;
}
function text(value: unknown, max = 4000): asserts value is string {
  if (typeof value !== "string" || !value || value.trim() !== value || value.length > max || /[\x00-\x1f\x7f]/.test(value)) invalid();
}
function integer(value: unknown, max = 10000): asserts value is number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0 || value > max) invalid();
}
function array(value: unknown, max = 1000): unknown[] { if (!Array.isArray(value) || value.length > max) return invalid(); return value; }
function strings(value: unknown): string[] { const items = array(value); items.forEach((item) => text(item)); return items as string[]; }
function stamp(value: unknown): asserts value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value)
    || !Number.isFinite(Date.parse(value)) || new Date(`${value.slice(0, 19)}Z`).toISOString().slice(0, 19) !== value.slice(0, 19)) invalid();
}
function day(value: unknown): asserts value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value) || !Number.isFinite(Date.parse(`${value}T00:00:00Z`))
    || new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) !== value) invalid();
}
function decimal(value: unknown): asserts value is string | null {
  if (value !== null && (typeof value !== "string" || value.length > 256 || !/^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(value) || !Number.isFinite(Number(value)))) invalid();
}
function hash(value: unknown): void { if (typeof value !== "string" || !/^[a-f0-9]{64}$/.test(value)) invalid(); }
const AUTHORITY = ["authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled"];
function authority(value: unknown) { if (Object.values(object(value, AUTHORITY)).some((item) => item !== false)) invalid(); }
function evidence(value: unknown) {
  const row = object(value, ["path", "sha256", "size_bytes"]);
  text(row.path, 256); hash(row.sha256); integer(row.size_bytes, 64 * 1024 * 1024);
  if (row.path.startsWith("/") || /[\\%]/.test(row.path) || row.path.split("/").some((part) => !part || part === "." || part === "..")) invalid();
}

/** Validate presentation shape and research-only declarations; do not calculate research results. */
export function validateShadowExperiment(value: unknown, now = Date.now()): ShadowExperimentFeed {
  const feed = object(value, ["schema_version", "checked_at", "status", "message", "experiment"]);
  if (feed.schema_version !== "blackpod.shadow_experiment_feed.v1" || !["READY", "NOT_CONFIGURED", "UNAVAILABLE"].includes(feed.status as string)) invalid();
  stamp(feed.checked_at); text(feed.message);
  if (Date.parse(feed.checked_at) > now + 5000) invalid();
  if (feed.status !== "READY") {
    if (feed.experiment !== null) invalid();
    return feed as unknown as ShadowExperimentFeed;
  }
  const view = object(feed.experiment, ["schema_version", "protocol", "journal", "predictions", "outcomes", "summary", "latest_captured_at", "auto_trading_enabled", "authority", "limitations"]);
  if (view.schema_version !== "blackpod.shadow_experiment_view.v1" || view.auto_trading_enabled !== false) invalid();
  const protocol = object(view.protocol, ["schema_version", "method_version", "experiment_id", "frozen_at", "first_signal_session", "universe", "sessions", "context_sessions", "hypothesis_evidence", "calendar_evidence", "calendar_receipt_evidence", "calendar_captured_at", "original_hypothesis_id", "original_horizon", "observation_basis", "availability_buffer_seconds", "criteria", "scope", "auto_trading_enabled", "authority", "execution_status", "realized_trade_pnl", "limitations"]);
  text(protocol.experiment_id, 256); stamp(protocol.frozen_at);
  if (protocol.schema_version !== "blackpod.shadow_experiment_protocol.v1" || protocol.method_version !== "blackpod.prospective_reversal_gross_proxy.v1"
    || protocol.original_hypothesis_id !== "previous-session-reversal-v1" || protocol.scope !== "PROSPECTIVE_OBSERVATION_ONLY"
    || protocol.observation_basis !== "PROVIDER_DAILY_BAR_OPEN_TO_OPEN_GROSS_PROXY" || protocol.availability_buffer_seconds !== 900
    || protocol.auto_trading_enabled !== false || protocol.execution_status !== "NOT_EXECUTED" || protocol.realized_trade_pnl !== null
    || Date.parse(protocol.frozen_at) > Date.parse(feed.checked_at) || JSON.stringify(protocol.universe) !== '["QQQ","SPY"]') invalid();
  authority(view.authority); authority(protocol.authority); strings(protocol.limitations);
  stamp(protocol.calendar_captured_at); day(protocol.first_signal_session);
  if (Date.parse(protocol.calendar_captured_at) > Date.parse(protocol.frozen_at)) invalid();
  for (const key of ["hypothesis_evidence", "calendar_evidence", "calendar_receipt_evidence"]) evidence(protocol[key]);
  const sessions = array(protocol.sessions, 30), context = array(protocol.context_sessions, 33);
  if (sessions.length !== 30 || context.length !== 33) invalid();
  for (const raw of context) {
    const row = object(raw, ["date", "open_at", "close_at", "session_open_at", "session_close_at"]);
    day(row.date); for (const key of ["open_at", "close_at", "session_open_at", "session_close_at"]) stamp(row[key]);
  }
  if (JSON.stringify(sessions) !== JSON.stringify(context.slice(1, 31)) || protocol.first_signal_session !== (sessions[0] as Record<string, unknown>).date) invalid();
  const criteria = object(protocol.criteria, ["signal_sessions", "opportunity_count", "minimum_observed_candidates", "candidate_rule", "holding_sessions", "overlap_policy", "cash_benchmark", "control_benchmark", "positive_descriptive_rule", "sample_unit", "inference", "cost_policy", "parameter_changes", "admission_deadline_seconds_before_source_session_open", "proxy_clock_basis", "source_completion", "arithmetic"]);
  if (criteria.signal_sessions !== 30 || criteria.opportunity_count !== 60 || criteria.minimum_observed_candidates !== 12 || criteria.holding_sessions !== 1
    || criteria.admission_deadline_seconds_before_source_session_open !== 300
    || criteria.cost_policy !== "UNKNOWN_NET_METRICS_UNAVAILABLE" || criteria.inference !== "DESCRIPTIVE_ONLY_NO_SIGNIFICANCE_OR_ECONOMIC_EDGE_CLAIM") invalid();
  for (const item of Object.values(criteria)) if (typeof item === "string") text(item);
  const horizon = object(protocol.original_horizon, ["kind", "holding_sessions", "label_horizon_sessions", "entry_clock", "exit_clock", "overlap_policy"]);
  if (horizon.kind !== "SWING" || horizon.holding_sessions !== 1 || horizon.label_horizon_sessions !== 1) invalid();
  strings(view.limitations);
  if (view.latest_captured_at !== null) { stamp(view.latest_captured_at); if (Date.parse(view.latest_captured_at) > Date.parse(feed.checked_at)) invalid(); }
  const journal = object(view.journal, ["event_count", "evidence_blob_count", "last_entry_sha256"]);
  integer(journal.event_count); integer(journal.evidence_blob_count); hash(journal.last_entry_sha256);
  const summary = object(view.summary, ["opportunity_count", "recorded_prediction_count", "pending_prediction_count", "candidate_count", "abstention_count", "missed_count", "missing_input_count", "observed_outcome_count", "pending_outcome_count", "mean_gross_return", "mean_gross_excess_over_control", "positive_gross_outcome_fraction", "conclusion", "economic_support", "net_return", "next_action"]);
  for (const [key, item] of Object.entries(summary)) {
    if (key.endsWith("_count")) integer(item, 60);
  }
  for (const key of ["mean_gross_return", "mean_gross_excess_over_control", "positive_gross_outcome_fraction"]) decimal(summary[key]);
  text(summary.conclusion);
  if (summary.economic_support !== "NOT_EVALUABLE" || summary.net_return !== null || summary.next_action !== "MANUAL_REVIEW_AFTER_PILOT_NO_AUTOMATIC_EXTENSION"
    || !["PENDING", "INCONCLUSIVE_MISSING_EVIDENCE", "INCONCLUSIVE_TOO_FEW_CANDIDATES", "DESCRIPTIVE_POSITIVE_PROXY_ONLY", "DESCRIPTIVE_NONPOSITIVE_PROXY"].includes(summary.conclusion)) invalid();
  if (summary.opportunity_count !== 60 || (summary.recorded_prediction_count as number) + (summary.pending_prediction_count as number) !== 60) invalid();
  const predictions = array(view.predictions, 60), ids = new Map<string, string>();
  for (const raw of predictions) {
    const row = object(raw, ["prediction_id", "symbol", "signal_session", "signal_close_at", "signal_available_at", "entry_session", "entry_open_at", "exit_session", "exit_open_at", "outcome_available_at", "recorded_at", "status", "reason_codes", "signal_return", "signal_close", "previous_close"]);
    text(row.prediction_id, 256); text(row.status, 100); strings(row.reason_codes); decimal(row.signal_return);
    if (!["OBSERVATIONAL_CANDIDATE", "ABSTAIN_NONNEGATIVE_RETURN", "ABSTAIN_OVERLAP", "DEFER_MISSING_INPUT", "MISSED_PREDICTION_DEADLINE"].includes(row.status)) invalid();
    if (!["QQQ", "SPY"].includes(row.symbol as string) || ids.has(row.prediction_id)) invalid();
    ids.set(row.prediction_id, row.symbol as string);
    for (const key of ["signal_session", "entry_session", "exit_session"]) day(row[key]);
    for (const key of ["signal_close_at", "signal_available_at", "entry_open_at", "exit_open_at", "outcome_available_at", "recorded_at"]) stamp(row[key]);
    decimal(row.signal_close); decimal(row.previous_close);
    if (Date.parse(row.recorded_at as string) > Date.parse(feed.checked_at)) invalid();
  }
  const outcomes = array(view.outcomes, 60), seen = new Set<string>();
  for (const raw of outcomes) {
    const row = object(raw, ["outcome_id", "prediction_id", "symbol", "recorded_at", "status", "candidate_gross_return", "control_gross_return", "cash_return", "excess_over_control", "reason_codes", "entry_price", "exit_price"]);
    text(row.outcome_id, 256); text(row.prediction_id, 256); text(row.status, 100); stamp(row.recorded_at); strings(row.reason_codes);
    if (!["OBSERVED_GROSS_PROXY_ONLY", "NOT_APPLICABLE_ABSTENTION", "UNMEASURABLE"].includes(row.status)) invalid();
    if (ids.get(row.prediction_id) !== row.symbol || seen.has(row.prediction_id) || Date.parse(row.recorded_at) > Date.parse(feed.checked_at)) invalid();
    seen.add(row.prediction_id);
    for (const key of ["candidate_gross_return", "control_gross_return", "cash_return", "excess_over_control"]) decimal(row[key]);
    decimal(row.entry_price); decimal(row.exit_price);
  }
  if (predictions.length !== summary.recorded_prediction_count) invalid();
  return feed as unknown as ShadowExperimentFeed;
}

export async function loadShadowExperiment({ signal }: { signal?: AbortSignal } = {}): Promise<ShadowExperimentFeed> {
  const response = await fetch(SHADOW_EXPERIMENT_URL, { method: "GET", signal, cache: "no-store", redirect: "error", credentials: "same-origin", headers: { Accept: "application/json" } });
  const length = response.headers.get("content-length");
  if (!response.ok || !/^application\/json(?:;|$)/i.test(response.headers.get("content-type") ?? "")
    || (length !== null && (!/^\d+$/.test(length) || Number(length) > SHADOW_EXPERIMENT_MAX_BYTES))) {
    await response.body?.cancel().catch(() => {}); return invalid();
  }
  if (!response.body) return invalid();
  const reader = response.body.getReader(), decoder = new TextDecoder("utf-8", { fatal: true });
  let size = 0, content = "";
  try {
    while (true) {
      if (signal?.aborted) return invalid();
      const { done, value } = await reader.read(); if (done) break;
      size += value.byteLength; if (size > SHADOW_EXPERIMENT_MAX_BYTES) return invalid();
      content += decoder.decode(value, { stream: true });
    }
    content += decoder.decode(); if (signal?.aborted) return invalid();
    return validateShadowExperiment(JSON.parse(content));
  } catch { return invalid(); }
  finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}
