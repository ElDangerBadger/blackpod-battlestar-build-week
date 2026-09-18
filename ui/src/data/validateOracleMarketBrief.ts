import {
  ORACLE_BRIEF_DRAFT_SCHEMA, ORACLE_BRIEF_EVIDENCE_SCHEMA, ORACLE_BRIEF_SECTIONS,
  ORACLE_BRIEF_SOURCES, ORACLE_MARKET_BRIEF_SCHEMA, type OracleMarketBrief,
} from "../contracts/oracleMarketBrief";
import { parseArtifactReference, PresentationContractError } from "./validate";

const invalid = (field: string): never => { throw new PresentationContractError(`Oracle market brief ${field} is invalid`); };
function object(value: unknown, keys: readonly string[], field: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return invalid(field);
  const item = value as Record<string, unknown>;
  if (Object.keys(item).length !== keys.length || keys.some((key) => !Object.hasOwn(item, key))) invalid(field);
  return item;
}
function text(value: unknown, field: string, maximum = 512): asserts value is string {
  if (typeof value !== "string" || !value.trim() || value !== value.trim() || value.length > maximum || /[\x00-\x1f\x7f-\x9f]/.test(value)) invalid(field);
}
function array(value: unknown, field: string, maximum = 128, minimum = 0): unknown[] {
  if (!Array.isArray(value) || value.length < minimum || value.length > maximum) return invalid(field);
  return value;
}
function hash(value: unknown, field: string) {
  if (typeof value !== "string" || !/^[a-f0-9]{64}$/.test(value)) invalid(field);
}
function id(value: unknown, prefix: string, field: string) {
  if (typeof value !== "string" || !value.startsWith(prefix)) invalid(field);
  hash((value as string).slice(prefix.length), field);
}
function time(value: unknown, field: string): number {
  text(value, field, 64);
  const parts = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(?:Z|([+-])(\d{2}):(\d{2}))$/.exec(value);
  const instant = Date.parse(value);
  if (!parts || !Number.isFinite(instant)) return invalid(field);
  const [, year, month, day, hour, minute, second] = parts.map(Number);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (year < 1 || month < 1 || month > 12 || day < 1 || day > days[month - 1] || hour > 23 || minute > 59 || second > 59
    || (parts[7] && (Number(parts[8]) > 23 || Number(parts[9]) > 59))) invalid(field);
  return instant;
}
function jsonValue(value: unknown): void {
  if (typeof value === "boolean") return;
  if (typeof value === "number") {
    if (!Number.isFinite(value) || (Number.isInteger(value) && !Number.isSafeInteger(value))) invalid("fact value number");
    return;
  }
  if (typeof value === "string") {
    text(value, "fact value text", 2000);
    return;
  }
  if (Array.isArray(value)) {
    if (value.length > 100 || new Set(value).size !== value.length) invalid("fact value array");
    value.forEach((entry) => text(entry, "fact value entry", 1024)); return;
  }
  invalid("fact value");
}

/** Transport checks only. The loader binds exact verified source bytes and facts. */
export function validateOracleMarketBrief(value: unknown): OracleMarketBrief {
  const brief = object(value, ["schema_version", "brief_id", "evidence", "report", "generated_at", "provenance", "generation_method", "observation_only", "order_submission_enabled", "authoritative", "validation_status"], "fields");
  if (brief.schema_version !== ORACLE_MARKET_BRIEF_SCHEMA || brief.generation_method !== "MODELDOCK_GROUNDED_SYNTHESIS"
    || brief.observation_only !== true || brief.order_submission_enabled !== false || brief.authoritative !== false
    || brief.validation_status !== "STRUCTURE_CITATIONS_AND_GUARDRAILS_CHECKED_NOT_ENTAILMENT_VERIFIED") invalid("safety or version");
  id(brief.brief_id, "oracle-market-brief-", "identity");
  const evidence = object(brief.evidence, ["schema_version", "evidence_id", "mission_id", "request_id", "symbol", "run_mode", "as_of", "source_artifacts", "facts", "warnings", "blockers", "limitations"], "evidence");
  if (evidence.schema_version !== ORACLE_BRIEF_EVIDENCE_SCHEMA || evidence.run_mode !== "LIVE") invalid("evidence version/mode");
  id(evidence.evidence_id, "oracle-brief-evidence-", "evidence identity");
  for (const key of ["mission_id", "request_id"]) text(evidence[key], key, 256);
  if (evidence.mission_id === evidence.request_id) invalid("mission identity");
  text(evidence.symbol, "symbol", 16); if (!/^[A-Z][A-Z0-9.\-^]{0,15}$/.test(evidence.symbol)) invalid("symbol");
  const asOf = time(evidence.as_of, "market time");
  const sources = object(evidence.source_artifacts, ORACLE_BRIEF_SOURCES, "sources");
  const sourceNames = [...ORACLE_BRIEF_SOURCES] as string[];
  for (const name of sourceNames) {
    const raw = sources[name];
    object(raw, ["name", "path", "sha256", "producer", "byte_size", "schema_version", "observed_at"], "source reference");
    const source = parseArtifactReference(raw, "Oracle market brief source");
    if (source.name !== name || /[%?#:\x00-\x1f\x7f]/.test(source.path)
      || source.path.length > 512 || source.byte_size === null || source.byte_size < 1 || source.byte_size > 256 * 1024
      || !Number.isSafeInteger(source.byte_size)) invalid("source reference");
    text(source.producer, "source producer", 256);
    time(source.observed_at, "source timestamp");
  }
  if (new Set(sourceNames).size !== 5) invalid("unique sources");
  const facts = array(evidence.facts, "facts", 128, 1), ids = new Set<string>();
  for (const raw of facts) {
    const fact = object(raw, ["fact_id", "source_artifact", "json_pointer", "label", "value", "meaning"], "fact");
    text(fact.fact_id, "fact identity", 128);
    if (!/^[A-Za-z0-9_.:-]+$/.test(fact.fact_id) || ids.has(fact.fact_id)) invalid("fact identity");
    ids.add(fact.fact_id);
    if (typeof fact.source_artifact !== "string" || !sourceNames.includes(fact.source_artifact)) invalid("fact source");
    text(fact.json_pointer, "fact pointer", 512);
    if (!fact.json_pointer.startsWith("/") || /~(?![01])/.test(fact.json_pointer)) invalid("fact pointer");
    text(fact.label, "fact label", 256); text(fact.meaning, "fact meaning", 2000); jsonValue(fact.value);
  }
  for (const key of ["warnings", "blockers", "limitations"]) {
    const values = array(evidence[key], key, 500);
    if (new Set(values).size !== values.length) invalid(key);
    values.forEach((entry) => text(entry, key, 1024));
  }
  const report = object(brief.report, ["schema_version", "headline", "sections"], "report");
  if (report.schema_version !== ORACLE_BRIEF_DRAFT_SCHEMA) invalid("report version");
  function paragraph(value: unknown, maximum = 1200) {
    const part = object(value, ["text", "fact_ids"], "paragraph"); text(part.text, "paragraph text", maximum);
    const citations = array(part.fact_ids, "citations", 8, 1);
    if (new Set(citations).size !== citations.length || citations.some((ref) => typeof ref !== "string" || !ids.has(ref))) invalid("citation identity");
  }
  paragraph(report.headline, 240);
  const sections = array(report.sections, "sections", 6, 6);
  sections.forEach((raw, index) => {
    const section = object(raw, ["section_id", "paragraphs"], "section");
    if (section.section_id !== ORACLE_BRIEF_SECTIONS[index]) invalid("section order");
    array(section.paragraphs, "section paragraphs", 2, 1).forEach((part) => paragraph(part));
  });
  const provenance = object(brief.provenance, ["provider", "model", "model_revision", "trace_id", "mocked", "request_sha256", "response_sha256", "started_at", "observed_at", "canonical_module_sha256"], "provenance");
  for (const key of ["model", "trace_id"]) {
    text(provenance[key], key, 256);
    if (!/^[A-Za-z0-9][A-Za-z0-9_.:@+/\-]{0,255}$/.test(provenance[key]) || provenance[key].includes("..")) invalid(key);
  }
  if (provenance.model_revision !== null) text(provenance.model_revision, "model revision", 256);
  if (provenance.provider !== "mlx" || provenance.mocked !== false) invalid("real inference provenance");
  for (const key of ["request_sha256", "response_sha256", "canonical_module_sha256"]) hash(provenance[key], key);
  const started = time(provenance.started_at, "inference start"), observed = time(provenance.observed_at, "inference response"), generated = time(brief.generated_at, "generation time");
  if (asOf > started || started > observed || observed > generated) invalid("timestamp ordering");
  for (const raw of Object.values(sources)) {
    if (time((raw as Record<string, unknown>).observed_at, "source observation") > started) invalid("source after inference");
  }
  return value as OracleMarketBrief;
}
