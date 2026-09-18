import type { SentryScanFeed } from "../contracts/sentryScan";

export const SENTRY_SCAN_URL = "/live/sentry/scan.json";
export const SENTRY_SCAN_MAX_BYTES = 256 * 1024;
const PROFILES = ["GENERAL_EQUITY", "ETF"];
const invalid = (): never => { throw new Error("Recorded Sentry scan is unavailable or invalid."); };
function object(value: unknown, keys: string[]): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return invalid();
  const result = value as Record<string, unknown>;
  if (Object.keys(result).length !== keys.length || keys.some((key) => !Object.hasOwn(result, key))) invalid();
  return result;
}
function text(value: unknown, max = 512): asserts value is string {
  if (typeof value !== "string" || !value || value.trim() !== value || value.length > max || /[\x00-\x1f\x7f]/.test(value)) invalid();
}
function identifier(value: unknown): asserts value is string { text(value, 256); if (!/^[A-Za-z0-9_.:-]+$/.test(value)) invalid(); }
function number(value: unknown, max = 1): asserts value is number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > max) invalid();
}
function integer(value: unknown, max = 128): asserts value is number { number(value, max); if (!Number.isSafeInteger(value)) invalid(); }
function boolean(value: unknown): asserts value is boolean { if (typeof value !== "boolean") invalid(); }
function list(value: unknown, max = 128): unknown[] { if (!Array.isArray(value) || value.length > max) return invalid(); return value; }
function strings(value: unknown, max = 128): string[] { const items = list(value, max); items.forEach((item) => text(item)); return items as string[]; }
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
function symbols(value: unknown): string[] {
  const items = list(value); items.forEach(symbol);
  if (JSON.stringify(items) !== JSON.stringify([...new Set(items)].sort())) invalid();
  return items as string[];
}
function file(value: Record<string, unknown>, max = 64 * 1024 * 1024) {
  text(value.file_name, 255); hash(value.sha256); integer(value.byte_size, max);
  if (/[\\/]/.test(value.file_name) || value.file_name.includes("..") || value.file_name === ".") invalid();
}

/** Validate the small presentation contract; do not recompute scientific results. */
export function validateSentryScanFeed(value: unknown, now = Date.now()): SentryScanFeed {
  const item = object(value, ["schema_version", "checked_at", "status", "message", "source", "scan", "observation_only", "order_submission_enabled", "current_attention_published"]);
  if (item.schema_version !== "blackpod.sentry_scan_feed.v1" || !["READY", "UNAVAILABLE", "NOT_CONFIGURED"].includes(item.status as string)
    || item.observation_only !== true || item.order_submission_enabled !== false || item.current_attention_published !== false) invalid();
  stamp(item.checked_at); text(item.message);
  if (Date.parse(item.checked_at) > now + 5000) invalid();
  if (item.status !== "READY") {
    if (item.source !== null || item.scan !== null) invalid();
    return item as unknown as SentryScanFeed;
  }
  const source = object(item.source, ["file_name", "sha256", "byte_size", "declared_evidence_reverified"]);
  file(source, 16 * 1024 * 1024); if (source.declared_evidence_reverified !== false) invalid();
  const scan = object(item.scan, ["scan_id", "scan_kind", "session_date", "as_of", "manifest_sha256", "reference_manifest_id", "validation_protocol_id", "calibration_ids", "configuration", "population", "symbols", "windows", "profile_statuses", "limitations"]);
  for (const key of ["scan_id", "reference_manifest_id", "validation_protocol_id"]) identifier(scan[key]);
  if (scan.scan_kind !== "OFFLINE_RESEARCH_SNAPSHOT") invalid();
  hash(scan.manifest_sha256); day(scan.session_date); stamp(scan.as_of);
  if (scan.session_date >= scan.as_of.slice(0, 10) || Date.parse(scan.as_of) > Date.parse(item.checked_at)) invalid();
  const calibrations = list(scan.calibration_ids, 100); calibrations.forEach(identifier);
  if (!calibrations.length || JSON.stringify(calibrations) !== JSON.stringify([...new Set(calibrations)].sort())) invalid();
  const profiles = object(scan.profile_statuses, PROFILES);
  if (Object.values(profiles).some((profile) => profile !== "RESEARCH_ONLY")) invalid();
  strings(scan.limitations, 40);
  const config = object(scan.configuration, ["windows", "minimum_history_sessions", "capacity", "minimum_percentile", "per_profile_capacity"]);
  if (JSON.stringify(config.windows) !== "[20,60]" || config.minimum_history_sessions !== 66) invalid();
  integer(config.capacity); number(config.minimum_percentile); if (config.minimum_percentile !== .95) invalid();
  const caps = object(config.per_profile_capacity, PROFILES); Object.values(caps).forEach((cap) => integer(cap));
  const population = object(scan.population, ["requested", "observed", "failed", "requested_count", "observed_count", "failed_count"]);
  const requested = symbols(population.requested), observed = symbols(population.observed), failed = symbols(population.failed);
  if (!requested.length || observed.some((name) => failed.includes(name)) || JSON.stringify([...observed, ...failed].sort()) !== JSON.stringify(requested)) invalid();
  for (const group of ["requested", "observed", "failed"]) {
    integer(population[`${group}_count`]); if (population[`${group}_count`] !== (population[group] as string[]).length) invalid();
  }
  const rows = list(scan.symbols), bySymbol = new Map<string, Record<string, unknown>>();
  for (const raw of rows) {
    const row = object(raw, ["symbol", "status", "reasons", "profile", "history", "failure_evidence", "history_validation"]);
    symbol(row.symbol); if (!requested.includes(row.symbol) || bySymbol.has(row.symbol)) invalid();
    bySymbol.set(row.symbol, row);
    const isObserved = observed.includes(row.symbol), reasons = strings(row.reasons);
    if (row.status !== (isObserved ? "OBSERVED" : "EXCLUDED") || (isObserved ? reasons.length !== 0 : !reasons.length) || (row.profile !== null && !PROFILES.includes(row.profile as string))) invalid();
    let history: Record<string, unknown> | null = null, validation: Record<string, unknown> | null = null;
    if (row.history !== null) {
      history = object(row.history, ["file_name", "sha256", "byte_size", "provider", "captured_at", "source_receipt_id", "first_session", "last_session", "row_count"]);
      file(history); identifier(history.provider); identifier(history.source_receipt_id); stamp(history.captured_at); integer(history.row_count, 1_000_000);
      if (Date.parse(history.captured_at) > Date.parse(scan.as_of)) invalid();
      for (const key of ["first_session", "last_session"]) if (history[key] !== null) day(history[key]);
    }
    if (row.failure_evidence !== null) {
      const failure = object(row.failure_evidence, ["file_name", "sha256", "byte_size", "receipt_id", "status"]);
      file(failure); identifier(failure.receipt_id); identifier(failure.status);
    }
    if (row.history_validation !== null) {
      validation = object(row.history_validation, ["report_id", "structurally_valid", "research_usable", "errors", "warnings"]);
      identifier(validation.report_id); boolean(validation.structurally_valid); boolean(validation.research_usable); strings(validation.errors); strings(validation.warnings);
    }
    if (isObserved && (!row.profile || !history || typeof history.first_session !== "string" || history.first_session > scan.session_date
      || history.last_session !== scan.session_date || (history.captured_at as string).slice(0, 10) <= scan.session_date || (history.row_count as number) < 66 || row.failure_evidence !== null
      || !validation || validation.research_usable !== true || validation.structurally_valid !== true || (validation.errors as unknown[]).length)) invalid();
  }
  if (JSON.stringify(rows.map((row) => (row as Record<string, unknown>).symbol)) !== JSON.stringify(requested)) invalid();
  const windows = list(scan.windows, 2);
  if (JSON.stringify(windows.map((window) => (window as Record<string, unknown>)?.lookback)) !== "[20,60]") invalid();
  for (const raw of windows) {
    const window = object(raw, ["lookback", "selection_id", "policy_id", "candidate_count", "eligible_candidate_count", "capacity_remaining", "selected", "excluded"]);
    identifier(window.selection_id); identifier(window.policy_id);
    integer(window.candidate_count); integer(window.eligible_candidate_count); integer(window.capacity_remaining);
    const selected = list(window.selected), excluded = list(window.excluded), seen: string[] = []; let eligible = 0;
    const profileCounts: Record<string, number> = { GENERAL_EQUITY: 0, ETF: 0 };
    for (const [group, entries] of [["selected", selected], ["excluded", excluded]] as const) {
      for (const rawEntry of entries) {
        const entry = object(rawEntry, ["symbol", "profile", "percentile", "metric_name", "sensor_result_id", "winning_assessment_id", "calibration_id", "reasons", "quality_flags"]);
        symbol(entry.symbol); identifier(entry.sensor_result_id);
        if (!observed.includes(entry.symbol) || entry.profile !== bySymbol.get(entry.symbol)?.profile) invalid();
        seen.push(entry.symbol); const reasons = strings(entry.reasons); strings(entry.quality_flags);
        if (entry.percentile !== null) {
          number(entry.percentile); identifier(entry.metric_name); identifier(entry.winning_assessment_id); identifier(entry.calibration_id);
          if (!calibrations.includes(entry.calibration_id)) invalid(); eligible++;
        } else if (entry.metric_name !== null || entry.winning_assessment_id !== null || entry.calibration_id !== null) invalid();
        if (group === "selected") {
          if (entry.percentile === null || (entry.percentile as number) < config.minimum_percentile || JSON.stringify(reasons) !== '["SELECTED"]') invalid();
          profileCounts[entry.profile as string]++;
        } else if (!reasons.length || reasons.includes("SELECTED")) invalid();
      }
    }
    if (JSON.stringify(seen.sort()) !== JSON.stringify(observed) || window.candidate_count !== observed.length || window.eligible_candidate_count !== eligible
      || selected.length > config.capacity || window.capacity_remaining !== config.capacity - selected.length
      || PROFILES.some((profile) => profileCounts[profile] > (caps[profile] as number))) invalid();
  }
  return item as unknown as SentryScanFeed;
}

export async function loadSentryScanFeed({ signal }: { signal?: AbortSignal } = {}): Promise<SentryScanFeed> {
  const response = await fetch(SENTRY_SCAN_URL, { method: "GET", signal, cache: "no-store", redirect: "error", credentials: "same-origin", headers: { Accept: "application/json" } });
  const length = response.headers.get("content-length");
  if (!response.ok || !/^application\/json(?:;|$)/i.test(response.headers.get("content-type") ?? "")
    || (length !== null && (!/^\d+$/.test(length) || Number(length) > SENTRY_SCAN_MAX_BYTES))) {
    await response.body?.cancel().catch(() => {}); return invalid();
  }
  if (!response.body) return invalid();
  const reader = response.body.getReader(), decoder = new TextDecoder("utf-8", { fatal: true });
  let size = 0, content = "";
  try {
    while (true) {
      if (signal?.aborted) return invalid();
      const { done, value } = await reader.read(); if (done) break;
      size += value.byteLength; if (size > SENTRY_SCAN_MAX_BYTES) return invalid();
      content += decoder.decode(value, { stream: true });
    }
    content += decoder.decode(); if (signal?.aborted) return invalid();
    return validateSentryScanFeed(JSON.parse(content));
  } catch { return invalid(); }
  finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}
