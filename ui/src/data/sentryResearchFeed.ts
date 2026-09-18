import { SENTRY_RESEARCH_ARMS, type SentryResearchFeed } from "../contracts/sentryResearch";

export const SENTRY_RESEARCH_URL = "/live/sentry/research.json";
export const SENTRY_RESEARCH_MAX_BYTES = 64 * 1024;
const invalid = (): never => { throw new Error("Sentry research checkpoint is unavailable or invalid."); };
function object(value: unknown, keys: string[]): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return invalid();
  const result = value as Record<string, unknown>;
  if (Object.keys(result).length !== keys.length || keys.some((key) => !Object.hasOwn(result, key))) invalid();
  return result;
}
function text(value: unknown, max = 4000): asserts value is string {
  if (typeof value !== "string" || !value.trim() || value.length > max || /[\x00-\x1f\x7f]/.test(value)) invalid();
}
function number(value: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): asserts value is number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < min || value > max) invalid();
}
function integer(value: unknown, max = Number.MAX_SAFE_INTEGER): asserts value is number {
  number(value, 0, max); if (!Number.isSafeInteger(value)) invalid();
}
function boolean(value: unknown): asserts value is boolean { if (typeof value !== "boolean") invalid(); }
function list(value: unknown, max: number): unknown[] {
  if (!Array.isArray(value) || value.length > max) return invalid();
  return value;
}
function day(value: unknown): asserts value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value) || !Number.isFinite(Date.parse(`${value}T00:00:00Z`))
    || new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) !== value) invalid();
}
function stamp(value: unknown): asserts value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value)
    || !Number.isFinite(Date.parse(value)) || new Date(`${value.slice(0, 19)}Z`).toISOString().slice(0, 19) !== value.slice(0, 19)) invalid();
}
function hash(value: unknown): void { if (typeof value !== "string" || !/^[a-f0-9]{64}$/.test(value)) invalid(); }
function symbol(value: unknown): asserts value is string { if (typeof value !== "string" || !/^[A-Z][A-Z0-9.-]{0,14}$/.test(value)) invalid(); }
function period(value: unknown): Record<string, string> {
  const item = object(value, ["start", "end"]); day(item.start); day(item.end);
  if (item.start > item.end) invalid();
  return item as Record<string, string>;
}
function stringList(value: unknown, max: number, width = 4000): string[] {
  const items = list(value, max); items.forEach((item) => text(item, width)); return items as string[];
}

/** Shape and consistency checks only; original supplied measurements remain unchanged. */
export function validateSentryResearchFeed(value: unknown, now = Date.now()): SentryResearchFeed {
  const item = object(value, ["schema_version", "checked_at", "status", "message", "source", "study", "prospective", "limitations", "observation_only", "order_submission_enabled", "current_attention_published"]);
  if (item.schema_version !== "blackpod.sentry_research_feed.v1" || !["READY", "UNAVAILABLE", "NOT_CONFIGURED"].includes(item.status as string)
    || item.observation_only !== true || item.order_submission_enabled !== false || item.current_attention_published !== false) invalid();
  stamp(item.checked_at); text(item.message, 512); stringList(item.limitations, 30);
  if (Date.parse(item.checked_at) > now + 5000) invalid();
  if (item.status !== "READY") {
    if (item.source !== null || item.study !== null || item.prospective !== null) invalid();
    return item as unknown as SentryResearchFeed;
  }
  const source = object(item.source, ["label", "kind", "archive_as_of", "files", "declared_upstream_hashes", "upstream_artifacts_reverified"]);
  text(source.label, 256); stamp(source.archive_as_of);
  if (source.kind !== "FIXED_RESEARCH_CHECKPOINT" || source.upstream_artifacts_reverified !== false || Date.parse(source.archive_as_of) > Date.parse(item.checked_at)) invalid();
  const files = list(source.files, 12);
  if (files.length !== 4) invalid();
  const fileNames: string[] = [];
  for (const raw of files) {
    const file = object(raw, ["file_name", "sha256", "byte_size"]);
    text(file.file_name, 255); hash(file.sha256); integer(file.byte_size, 128 * 1024);
    if (/[\\/]/.test(file.file_name) || file.file_name.includes("..") || file.file_name === ".") invalid();
    fileNames.push(file.file_name);
  }
  if (new Set(fileNames).size !== fileNames.length) invalid();
  const upstream = object(source.declared_upstream_hashes, ["cache", "results"]); hash(upstream.cache); hash(upstream.results);
  const study = object(item.study, ["development_id", "scope", "training_period", "development_period", "session_count", "cohort", "windows", "primary_arm", "profile_statuses", "criteria", "all_policies_failed", "policies"]);
  text(study.development_id, 256); text(study.scope, 512);
  const training = period(study.training_period), development = period(study.development_period);
  if (training.start !== "2019-01-01" || training.end !== "2022-12-31" || development.start !== "2023-01-01" || development.end !== "2024-12-31") invalid();
  integer(study.session_count, 10000); if (!study.session_count) invalid();
  const cohort = list(study.cohort, 56); cohort.forEach(symbol);
  if (cohort.length !== 56 || new Set(cohort).size !== 56 || JSON.stringify(study.windows) !== "[20,60]" || study.primary_arm !== "ELIGIBLE_INCUMBENT_FIRST") invalid();
  const profiles = object(study.profile_statuses, ["GENERAL_EQUITY", "ETF"]);
  if (profiles.GENERAL_EQUITY !== "RESEARCH_ONLY" || profiles.ETF !== "RESEARCH_ONLY") invalid();
  const criteria = object(study.criteria, ["mean_new_names_limit", "minimum_mean_jaccard", "capacity", "per_profile_capacity"]);
  if (criteria.mean_new_names_limit !== 2 || criteria.minimum_mean_jaccard !== 2 / 3 || criteria.capacity !== 6 || criteria.per_profile_capacity !== 4) invalid();
  if (study.all_policies_failed !== true) invalid();
  const policies = list(study.policies, 3); if (policies.length !== 3) invalid();
  const arms: string[] = [];
  for (const raw of policies) {
    const policy = object(raw, ["arm", "role", "windows", "mean_overlap", "meets_overlap", "meets_churn", "capped_by_construction"]);
    text(policy.arm, 80); arms.push(policy.arm);
    const armIndex = (SENTRY_RESEARCH_ARMS as readonly string[]).indexOf(policy.arm);
    if (armIndex < 0 || policy.role !== ["CONTROL", "PRIMARY", "EXPLORATORY"][armIndex]) invalid();
    number(policy.mean_overlap, 0, 1); boolean(policy.meets_overlap); boolean(policy.meets_churn); boolean(policy.capped_by_construction);
    if (policy.capped_by_construction !== (armIndex === 2) || policy.meets_overlap !== false || policy.meets_churn !== (armIndex === 2)) invalid();
    const windows = list(policy.windows, 2); if (windows.length !== 2) invalid();
    const seen: unknown[] = [];
    for (const rawWindow of windows) {
      const window = object(rawWindow, ["lookback", "mean_new_names_per_day", "new_names_total", "sessions", "mean_selected", "eligible_coverage", "top_symbols"]);
      if (window.lookback !== 20 && window.lookback !== 60) invalid(); seen.push(window.lookback);
      number(window.mean_new_names_per_day, 0, 6); integer(window.new_names_total, 6 * study.session_count);
      if (window.sessions !== study.session_count) invalid();
      number(window.mean_selected, 0, 6); number(window.eligible_coverage, 0, 1);
      const top = list(window.top_symbols, 6), names: string[] = [];
      for (const rawSymbol of top) {
        const entry = object(rawSymbol, ["symbol", "selected_sessions"]); symbol(entry.symbol); integer(entry.selected_sessions, study.session_count);
        if (!cohort.includes(entry.symbol)) invalid(); names.push(entry.symbol);
      }
      if (new Set(names).size !== names.length) invalid();
    }
    if (new Set(seen).size !== 2) invalid();
  }
  if (new Set(arms).size !== 3) invalid();
  const prospective = object(item.prospective, ["manifest_id", "period", "planned_sessions", "completed_sessions", "status", "warmup", "calendar_blocker_dates", "scheduler_loaded_at_archive"]);
  text(prospective.manifest_id, 256); const future = period(prospective.period); text(prospective.status, 256);
  if (future.start !== "2026-09-18" || future.end !== "2026-12-11" || prospective.planned_sessions !== 60) invalid();
  if (prospective.completed_sessions !== 0 || prospective.status !== "BLOCKED_MISSING_REQUIRED_EVIDENCE") invalid();
  boolean(prospective.scheduler_loaded_at_archive);
  const blockers = list(prospective.calendar_blocker_dates, 100); blockers.forEach(day);
  if (new Set(blockers).size !== blockers.length) invalid();
  const warmup = object(prospective.warmup, ["session", "status", "expected_symbols", "ready_symbols", "failed_symbols", "blocked_symbols", "complete_cohort_sealed", "failure_evidence_sealed", "provider_requests", "conflict", "first_captured_at", "last_captured_at"]);
  day(warmup.session); text(warmup.status, 256);
  if (warmup.session !== "2026-09-17" || warmup.expected_symbols !== cohort.length || warmup.status !== "FAILED_CLOSED_NOT_A_VALID_WARMUP") invalid();
  integer(warmup.ready_symbols, 56); integer(warmup.failed_symbols, 56); integer(warmup.blocked_symbols, 56); integer(warmup.provider_requests, 56);
  if (warmup.ready_symbols + warmup.failed_symbols + warmup.blocked_symbols !== 56) invalid();
  if (warmup.complete_cohort_sealed !== false || warmup.failure_evidence_sealed !== true) invalid();
  stamp(warmup.first_captured_at); stamp(warmup.last_captured_at);
  if (Date.parse(warmup.first_captured_at) > Date.parse(warmup.last_captured_at) || Date.parse(warmup.last_captured_at) > Date.parse(source.archive_as_of)) invalid();
  const conflict = object(warmup.conflict, ["symbol", "session", "fields", "prior_volume", "incoming_volume"]);
  symbol(conflict.symbol); day(conflict.session); if (!cohort.includes(conflict.symbol)) invalid();
  stringList(conflict.fields, 8, 64);
  for (const volume of [conflict.prior_volume, conflict.incoming_volume]) {
    if (typeof volume !== "string" || !/^\d{1,24}$/.test(volume)) invalid();
  }
  return item as unknown as SentryResearchFeed;
}

export async function loadSentryResearchFeed({ signal }: { signal?: AbortSignal } = {}): Promise<SentryResearchFeed> {
  const response = await fetch(SENTRY_RESEARCH_URL, { method: "GET", signal, cache: "no-store", redirect: "error", credentials: "same-origin", headers: { Accept: "application/json" } });
  const length = response.headers.get("content-length");
  if (!response.ok || !/^application\/json(?:;|$)/i.test(response.headers.get("content-type") ?? "")
    || (length !== null && (!/^\d+$/.test(length) || Number(length) > SENTRY_RESEARCH_MAX_BYTES))) {
    await response.body?.cancel().catch(() => {}); return invalid();
  }
  if (!response.body) return invalid();
  const reader = response.body.getReader(), decoder = new TextDecoder("utf-8", { fatal: true });
  let size = 0, content = "";
  try {
    while (true) {
      if (signal?.aborted) return invalid();
      const { done, value } = await reader.read(); if (done) break;
      size += value.byteLength; if (size > SENTRY_RESEARCH_MAX_BYTES) return invalid();
      content += decoder.decode(value, { stream: true });
    }
    content += decoder.decode(); if (signal?.aborted) return invalid();
    return validateSentryResearchFeed(JSON.parse(content));
  } catch { return invalid(); }
  finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}
