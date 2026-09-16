import {
  CANONICAL_STAGE_NAMES,
  CAPTAINS_LOG_SCHEMA,
  COMPONENT_STAGE_ORDER,
  DEMO_MANIFEST_SCHEMA,
  MISSION_SNAPSHOT_SCHEMA,
  MISSION_SUMMARY_SCHEMA,
  NAVIGATOR_ALLOWED_OPERATIONS,
  NAVIGATOR_PROHIBITED_OPERATIONS,
  PRESENTATION_STAGE_ORDER,
  PRESENTATION_MANIFEST_SCHEMA,
  type ApprovalScope,
  type ArtifactReference,
  type CaptainsLogEntry,
  type CaptainsLogV1,
  type CanonicalStageName,
  type CurrentPhase,
  type DemoManifestV1,
  type JsonObject,
  type JsonValue,
  type MissionOutcome,
  type MissionSnapshotV1,
  type MissionSummaryV2,
  type MissionManifest,
  type PresentationManifestV1,
  type ModelDockCallContract,
  type ModelDockDemoMode,
  type OperatorAction,
  type OperatorActionStatus,
  type OperatorResult,
  type OperatorRoute,
  type OrderedPresentationStage,
  type PresentationStage,
  type RunMode,
  type SnapshotNavigatorContract,
  type SnapshotOperatorContract,
  type SnapshotStageContract,
  type StageErrorContract,
  type StageStatus,
} from "../contracts/presentation";

export class PresentationContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PresentationContractError";
  }
}

const SHA256 = /^[0-9a-f]{64}$/;
const RFC3339 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
const STATUS_TOKEN = /^[A-Z][A-Z0-9_]{0,127}$/;

const RUN_MODES = ["LIVE", "REPLAY"] as const;
const MISSION_OUTCOMES = ["APPROVED", "HELD", "VETOED", "FAILED", "INCOMPLETE"] as const;
const CURRENT_PHASES = ["HARBORMASTER", "ORACLE", "COUNCIL", "GOVERNOR", "OPERATOR", "NAVIGATOR", "COMPLETE"] as const;
const STAGE_STATUSES = ["NOT_STARTED", "RUNNING", "SUCCEEDED", "FAILED", "SKIPPED"] as const;
const OPERATOR_ROUTES = ["PENDING_APPROVAL", "PENDING_REVIEW", "CLOSED_BLOCKED", "CLOSED_NO_ACTION"] as const;
const OPERATOR_ACTION_STATUSES = ["NOT_STARTED", "RUNNING", "SUCCEEDED", "FAILED"] as const;
const OPERATOR_ACTIONS = ["APPROVE_HANDOFF", "REJECT"] as const;
const OPERATOR_RESULTS = ["APPROVED_FOR_HANDOFF", "REJECTED"] as const;
const MODELDOCK_MODES = ["REPLAYED", "LIVE", "DISABLED", "FAILED"] as const;

export interface PrimaryMissionContracts {
  summary: MissionSummaryV2;
  captainsLog: CaptainsLogV1;
  manifest: MissionManifest;
  snapshot: MissionSnapshotV1;
}

function objectValue(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new PresentationContractError(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, keys: readonly string[], label: string): void {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  const missing = expected.filter((key) => !actual.includes(key));
  const unknown = actual.filter((key) => !expected.includes(key));
  if (missing.length > 0 || unknown.length > 0) {
    const details = [
      missing.length > 0 ? `missing ${missing.join(", ")}` : "",
      unknown.length > 0 ? `unknown ${unknown.join(", ")}` : "",
    ].filter(Boolean).join("; ");
    throw new PresentationContractError(`${label} has invalid fields: ${details}`);
  }
}

function stringValue(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0 || value.trim() !== value) {
    throw new PresentationContractError(`${label} must be a nonblank trimmed string`);
  }
  return value;
}

function nullableString(value: unknown, label: string): string | null {
  return value === null ? null : stringValue(value, label);
}

function booleanValue(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") {
    throw new PresentationContractError(`${label} must be a boolean`);
  }
  return value;
}

function nonnegativeInteger(value: unknown, label: string): number {
  if (!Number.isInteger(value) || (value as number) < 0) {
    throw new PresentationContractError(`${label} must be a nonnegative integer`);
  }
  return value as number;
}

function positiveInteger(value: unknown, label: string): number {
  const parsed = nonnegativeInteger(value, label);
  if (parsed === 0) {
    throw new PresentationContractError(`${label} must be positive`);
  }
  return parsed;
}

function finiteNumberOrNull(value: unknown, label: string): number | null {
  if (value === null) return null;
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    throw new PresentationContractError(`${label} must be null or a nonnegative number`);
  }
  return value;
}

function enumValue<T extends string>(value: unknown, allowed: readonly T[], label: string): T {
  if (typeof value !== "string" || !allowed.includes(value as T)) {
    throw new PresentationContractError(`${label} contains an unsupported value`);
  }
  return value as T;
}

function enumOrNull<T extends string>(value: unknown, allowed: readonly T[], label: string): T | null {
  return value === null ? null : enumValue(value, allowed, label);
}

function timestamp(value: unknown, label: string): string {
  const parsed = stringValue(value, label);
  if (!RFC3339.test(parsed) || Number.isNaN(Date.parse(parsed))) {
    throw new PresentationContractError(`${label} must be an RFC 3339 timestamp`);
  }
  return parsed;
}

function stringArray(value: unknown, label: string): string[] {
  if (!Array.isArray(value)) {
    throw new PresentationContractError(`${label} must be an array`);
  }
  return value.map((entry, index) => stringValue(entry, `${label}[${index}]`));
}

function uniqueStrings(values: string[], label: string): string[] {
  if (new Set(values).size !== values.length) {
    throw new PresentationContractError(`${label} values must be unique`);
  }
  return values;
}

export function isMissionRelativePath(value: string): boolean {
  if (!value || value.startsWith("/") || value.startsWith("~") || value.includes("\\")) return false;
  if (/^[A-Za-z]:/.test(value) || /^[a-z][a-z0-9+.-]*:\/\//i.test(value)) return false;
  const parts = value.split("/");
  return parts.every((part) => part.length > 0 && part !== "." && part !== "..");
}

function relativePath(value: unknown, label: string): string {
  const parsed = stringValue(value, label);
  if (!isMissionRelativePath(parsed)) {
    throw new PresentationContractError(`${label} must be a mission-relative POSIX path`);
  }
  return parsed;
}

export function parseArtifactReference(value: unknown, label = "artifact reference"): ArtifactReference {
  const item = objectValue(value, label);
  const legacy = Object.keys(item).length === 3 && ["name", "path", "sha256"].every((key) => Object.hasOwn(item, key));
  exactKeys(item, legacy ? ["name", "path", "sha256"]
    : ["name", "path", "sha256", "producer", "byte_size", "schema_version", "observed_at"], label);
  const digest = stringValue(item.sha256, `${label}.sha256`);
  if (!SHA256.test(digest)) {
    throw new PresentationContractError(`${label}.sha256 must be lowercase SHA-256`);
  }
  const byteSize = legacy || item.byte_size === null ? null : nonnegativeInteger(item.byte_size, `${label}.byte_size`);
  return {
    name: stringValue(item.name, `${label}.name`),
    path: relativePath(item.path, `${label}.path`),
    sha256: digest,
    producer: legacy ? null : nullableString(item.producer, `${label}.producer`),
    byte_size: byteSize,
    schema_version: legacy ? null : nullableString(item.schema_version, `${label}.schema_version`),
    observed_at: legacy || item.observed_at === null ? null : timestamp(item.observed_at, `${label}.observed_at`),
  };
}

function parseStageError(value: unknown, label: string): StageErrorContract | null {
  if (value === null) return null;
  const item = objectValue(value, label);
  exactKeys(item, ["code", "error_type", "message", "resumable", "observed_at"], label);
  return {
    code: stringValue(item.code, `${label}.code`),
    error_type: stringValue(item.error_type, `${label}.error_type`),
    message: stringValue(item.message, `${label}.message`),
    resumable: booleanValue(item.resumable, `${label}.resumable`),
    observed_at: timestamp(item.observed_at, `${label}.observed_at`),
  };
}

function parseModelDockCall(value: unknown, label: string): ModelDockCallContract {
  const item = objectValue(value, label);
  exactKeys(item, [
    "call_id", "status", "mission_id", "request_id", "run_mode", "endpoint", "provider", "model",
    "model_revision", "trace_id", "mocked", "latency_ms", "request_sha256", "response_sha256",
    "response_byte_size", "started_at", "observed_at", "artifacts", "error",
  ], label);
  const requestHash = stringValue(item.request_sha256, `${label}.request_sha256`);
  const responseHash = item.response_sha256 === null ? null : stringValue(item.response_sha256, `${label}.response_sha256`);
  if (!SHA256.test(requestHash) || (responseHash !== null && !SHA256.test(responseHash))) {
    throw new PresentationContractError(`${label} contains an invalid SHA-256 digest`);
  }
  return {
    call_id: stringValue(item.call_id, `${label}.call_id`),
    status: enumValue(item.status, ["RUNNING", "SUCCEEDED", "FAILED"] as const, `${label}.status`),
    mission_id: stringValue(item.mission_id, `${label}.mission_id`),
    request_id: stringValue(item.request_id, `${label}.request_id`),
    run_mode: enumValue(item.run_mode, RUN_MODES, `${label}.run_mode`),
    endpoint: stringValue(item.endpoint, `${label}.endpoint`),
    provider: nullableString(item.provider, `${label}.provider`),
    model: nullableString(item.model, `${label}.model`),
    model_revision: nullableString(item.model_revision, `${label}.model_revision`),
    trace_id: nullableString(item.trace_id, `${label}.trace_id`),
    mocked: item.mocked === null ? null : booleanValue(item.mocked, `${label}.mocked`),
    latency_ms: finiteNumberOrNull(item.latency_ms, `${label}.latency_ms`),
    request_sha256: requestHash,
    response_sha256: responseHash,
    response_byte_size: item.response_byte_size === null ? null : nonnegativeInteger(item.response_byte_size, `${label}.response_byte_size`),
    started_at: timestamp(item.started_at, `${label}.started_at`),
    observed_at: timestamp(item.observed_at, `${label}.observed_at`),
    artifacts: uniqueStrings(stringArray(item.artifacts, `${label}.artifacts`), `${label}.artifacts`),
    error: parseStageError(item.error, `${label}.error`),
  };
}

function parseSnapshotStage(value: unknown, label: string): SnapshotStageContract {
  const item = objectValue(value, label);
  // Canonical v1 accepts exactly the original pair, Stage 1 I/O, or current
  // fields. Missing parts of one variant are not silently repaired.
  const legacy = Object.keys(item).length === 2 && Object.hasOwn(item, "status") && Object.hasOwn(item, "native_state");
  exactKeys(item, legacy ? ["status", "native_state"]
    : ["status", "native_state", "inputs", "outputs", "error", ...(Object.hasOwn(item, "modeldock_calls") ? ["modeldock_calls"] : [])], label);
  const calls = Object.hasOwn(item, "modeldock_calls") ? item.modeldock_calls : [];
  if (!Array.isArray(calls)) {
    throw new PresentationContractError(`${label}.modeldock_calls must be an array`);
  }
  return {
    status: enumValue(item.status, STAGE_STATUSES, `${label}.status`),
    native_state: nullableString(item.native_state, `${label}.native_state`),
    inputs: legacy ? [] : uniqueStrings(stringArray(item.inputs, `${label}.inputs`), `${label}.inputs`),
    outputs: legacy ? [] : uniqueStrings(stringArray(item.outputs, `${label}.outputs`), `${label}.outputs`),
    error: legacy ? null : parseStageError(item.error, `${label}.error`),
    modeldock_calls: calls.map((call, index) => parseModelDockCall(call, `${label}.modeldock_calls[${index}]`)),
  };
}

function parseSnapshotOperator(value: unknown): SnapshotOperatorContract {
  const item = objectValue(value, "mission snapshot operator");
  const legacyFields = ["route", "action", "result", "operator_id", "acted_at"];
  if (Object.keys(item).length === legacyFields.length && legacyFields.every((key) => Object.hasOwn(item, key))) {
    if (legacyFields.some((key) => key !== "route" && item[key] !== null)) {
      throw new PresentationContractError("legacy operator action fields must remain null");
    }
    return {
      route: enumOrNull(item.route, OPERATOR_ROUTES, "operator.route"), action_status: "NOT_STARTED",
      action: null, result: null, action_id: null, operator_id: null, acted_at: null, error: null,
    };
  }
  exactKeys(item, ["route", "action_status", "action", "result", "action_id", "operator_id", "acted_at", "error"], "mission snapshot operator");
  return {
    route: enumOrNull(item.route, OPERATOR_ROUTES, "operator.route"),
    action_status: enumValue(item.action_status, OPERATOR_ACTION_STATUSES, "operator.action_status"),
    action: enumOrNull(item.action, OPERATOR_ACTIONS, "operator.action"),
    result: enumOrNull(item.result, OPERATOR_RESULTS, "operator.result"),
    action_id: nullableString(item.action_id, "operator.action_id"),
    operator_id: nullableString(item.operator_id, "operator.operator_id"),
    acted_at: item.acted_at === null ? null : timestamp(item.acted_at, "operator.acted_at"),
    error: parseStageError(item.error, "operator.error"),
  };
}

function parseSnapshotNavigator(value: unknown): SnapshotNavigatorContract {
  const item = objectValue(value, "mission snapshot navigator");
  exactKeys(item, [
    "mode", "handoff_status", "intake_status", "plan_status", "handoff_id", "intake_receipt_id",
    "plan_id", "expires_at", "idempotency_key", "allowed_operations", "prohibited_operations",
  ], "mission snapshot navigator");
  return {
    mode: enumOrNull(item.mode, ["SHADOW"] as const, "navigator.mode"),
    handoff_status: enumOrNull(item.handoff_status, ["STAGED"] as const, "navigator.handoff_status"),
    intake_status: enumOrNull(item.intake_status, ["ACCEPTED", "REJECTED"] as const, "navigator.intake_status"),
    plan_status: enumOrNull(item.plan_status, ["CREATED"] as const, "navigator.plan_status"),
    handoff_id: nullableString(item.handoff_id, "navigator.handoff_id"),
    intake_receipt_id: nullableString(item.intake_receipt_id, "navigator.intake_receipt_id"),
    plan_id: nullableString(item.plan_id, "navigator.plan_id"),
    expires_at: item.expires_at === null ? null : timestamp(item.expires_at, "navigator.expires_at"),
    idempotency_key: nullableString(item.idempotency_key, "navigator.idempotency_key"),
    allowed_operations: uniqueStrings(stringArray(item.allowed_operations, "navigator.allowed_operations"), "navigator.allowed_operations"),
    prohibited_operations: uniqueStrings(stringArray(item.prohibited_operations, "navigator.prohibited_operations"), "navigator.prohibited_operations"),
  };
}

function parseJsonObjectRecord(value: unknown, label: string): Record<string, JsonObject> {
  const item = objectValue(value, label);
  return Object.fromEntries(Object.entries(item).map(([key, child]) => [key, objectValue(child, `${label}.${key}`) as JsonObject]));
}

export function parseMissionSnapshot(value: unknown): MissionSnapshotV1 {
  const item = objectValue(value, "mission snapshot");
  exactKeys(item, [
    "schema_version", "snapshot_id", "mission_id", "request_id", "revision", "previous_snapshot_sha256",
    "run_mode", "started_at", "observed_at", "mission_outcome", "current_phase", "terminal", "stages",
    "artifacts", ...["components", "operator", "navigator", "approval_scope"].filter((key) => Object.hasOwn(item, key)),
  ], "mission snapshot");
  if (item.schema_version !== MISSION_SNAPSHOT_SCHEMA) {
    throw new PresentationContractError(`unsupported mission snapshot schema: ${String(item.schema_version)}`);
  }
  const stageObject = objectValue(item.stages, "mission snapshot stages");
  exactKeys(stageObject, CANONICAL_STAGE_NAMES, "mission snapshot stages");
  const stages = Object.fromEntries(CANONICAL_STAGE_NAMES.map((name) => [name, parseSnapshotStage(stageObject[name], `stages.${name}`)])) as Record<CanonicalStageName, SnapshotStageContract>;
  if (!Array.isArray(item.artifacts)) {
    throw new PresentationContractError("mission snapshot artifacts must be an array");
  }
  const artifacts = item.artifacts.map((artifact, index) => parseArtifactReference(artifact, `artifacts[${index}]`));
  if (new Set(artifacts.map((artifact) => artifact.name)).size !== artifacts.length) {
    throw new PresentationContractError("mission snapshot artifact names must be unique");
  }
  const previous = item.previous_snapshot_sha256 === null ? null : stringValue(item.previous_snapshot_sha256, "previous_snapshot_sha256");
  if (previous !== null && !SHA256.test(previous)) {
    throw new PresentationContractError("previous_snapshot_sha256 must be null or SHA-256");
  }
  return {
    schema_version: MISSION_SNAPSHOT_SCHEMA,
    snapshot_id: stringValue(item.snapshot_id, "snapshot_id"),
    mission_id: stringValue(item.mission_id, "mission_id"),
    request_id: stringValue(item.request_id, "request_id"),
    revision: positiveInteger(item.revision, "revision"),
    previous_snapshot_sha256: previous,
    run_mode: enumValue(item.run_mode, RUN_MODES, "run_mode"),
    started_at: timestamp(item.started_at, "started_at"),
    observed_at: timestamp(item.observed_at, "observed_at"),
    mission_outcome: enumValue(item.mission_outcome, MISSION_OUTCOMES, "mission_outcome"),
    current_phase: enumValue(item.current_phase, CURRENT_PHASES, "current_phase"),
    terminal: booleanValue(item.terminal, "terminal"),
    stages,
    artifacts,
    components: Object.hasOwn(item, "components") ? parseJsonObjectRecord(item.components, "components") : {},
    operator: Object.hasOwn(item, "operator") ? parseSnapshotOperator(item.operator) : {
      route: null, action_status: "NOT_STARTED", action: null, result: null, action_id: null,
      operator_id: null, acted_at: null, error: null,
    },
    navigator: Object.hasOwn(item, "navigator") ? parseSnapshotNavigator(item.navigator) : {
      mode: null, handoff_status: null, intake_status: null, plan_status: null, handoff_id: null,
      intake_receipt_id: null, plan_id: null, expires_at: null, idempotency_key: null,
      allowed_operations: [], prohibited_operations: [],
    },
    approval_scope: Object.hasOwn(item, "approval_scope")
      ? enumOrNull(item.approval_scope, ["NAVIGATOR_SHADOW_HANDOFF"] as const, "approval_scope") as ApprovalScope | null : null,
  };
}

function parseSummaryStage(value: unknown, label: string) {
  const item = objectValue(value, label);
  exactKeys(item, ["technical_status", "native_state"], label);
  return {
    technical_status: enumValue(item.technical_status, STAGE_STATUSES, `${label}.technical_status`),
    native_state: nullableString(item.native_state, `${label}.native_state`),
  };
}

function parseOrderedStage(value: unknown, label: string): OrderedPresentationStage {
  const item = objectValue(value, label);
  exactKeys(item, ["stage", "display_state", "summary", "artifact_paths"], label);
  return {
    stage: enumValue(item.stage, COMPONENT_STAGE_ORDER, `${label}.stage`),
    display_state: stringValue(item.display_state, `${label}.display_state`),
    summary: stringValue(item.summary, `${label}.summary`),
    artifact_paths: uniqueStrings(stringArray(item.artifact_paths, `${label}.artifact_paths`).map((path, index) => relativePath(path, `${label}.artifact_paths[${index}]`)), `${label}.artifact_paths`),
  };
}

export function parseMissionSummary(value: unknown): MissionSummaryV2 {
  const item = objectValue(value, "mission summary");
  exactKeys(item, [
    "schema_version", "mission_id", "request_id", "symbol", "run_mode", "generated_at", "generated_from_snapshot",
    "current_phase", "terminal", "stages", "modeldock", "governor_disposition", "operator", "navigator",
    "approval_scope", "final_outcome", "important_warnings", "snapshot_count", "canonical_snapshot_path",
    "display_title", "subtitle", "ordered_stages", "resumable", "event_count", "artifact_links",
  ], "mission summary");
  if (item.schema_version !== MISSION_SUMMARY_SCHEMA) {
    throw new PresentationContractError(`unsupported mission summary schema: ${String(item.schema_version)}`);
  }
  const stageObject = objectValue(item.stages, "mission summary stages");
  exactKeys(stageObject, CANONICAL_STAGE_NAMES, "mission summary stages");
  const stages = Object.fromEntries(CANONICAL_STAGE_NAMES.map((name) => [name, parseSummaryStage(stageObject[name], `stages.${name}`)])) as MissionSummaryV2["stages"];

  const modeldock = objectValue(item.modeldock, "mission summary modeldock");
  exactKeys(modeldock, ["status", "provider", "model", "trace_id"], "mission summary modeldock");
  const operator = objectValue(item.operator, "mission summary operator");
  exactKeys(operator, ["route", "action_status", "action", "result"], "mission summary operator");
  const navigator = objectValue(item.navigator, "mission summary navigator");
  exactKeys(navigator, ["technical_status", "native_state", "mode", "handoff_status", "intake_status", "plan_status"], "mission summary navigator");
  if (!Array.isArray(item.ordered_stages)) throw new PresentationContractError("ordered_stages must be an array");
  const ordered = item.ordered_stages.map((stage, index) => parseOrderedStage(stage, `ordered_stages[${index}]`));
  if (ordered.map((stage) => stage.stage).join("|") !== COMPONENT_STAGE_ORDER.join("|")) {
    throw new PresentationContractError("ordered_stages must use canonical order");
  }
  const links = objectValue(item.artifact_links, "mission summary artifact_links");
  exactKeys(links, ["captains_log_json", "captains_log_markdown", "mission_summary", "canonical_snapshot"], "mission summary artifact_links");
  const warningValues = uniqueStrings(stringArray(item.important_warnings, "important_warnings"), "important_warnings");
  const terminal = booleanValue(item.terminal, "terminal");
  const resumable = booleanValue(item.resumable, "resumable");
  if (resumable === terminal) throw new PresentationContractError("resumable must be the inverse of terminal");
  const eventCount = positiveInteger(item.event_count, "event_count");
  if (eventCount !== PRESENTATION_STAGE_ORDER.length) throw new PresentationContractError("event_count must equal canonical log length");
  if (item.canonical_snapshot_path !== "mission_snapshot.json") throw new PresentationContractError("canonical_snapshot_path is not canonical");
  const artifactLinks = {
    captains_log_json: relativePath(links.captains_log_json, "artifact_links.captains_log_json"),
    captains_log_markdown: relativePath(links.captains_log_markdown, "artifact_links.captains_log_markdown"),
    mission_summary: relativePath(links.mission_summary, "artifact_links.mission_summary"),
    canonical_snapshot: relativePath(links.canonical_snapshot, "artifact_links.canonical_snapshot"),
  };
  if (artifactLinks.captains_log_json !== "presentation/captains_log.json" || artifactLinks.captains_log_markdown !== "presentation/captains_log.md" || artifactLinks.mission_summary !== "presentation/mission_summary.json" || artifactLinks.canonical_snapshot !== "mission_snapshot.json") {
    throw new PresentationContractError("mission summary artifact links are not canonical");
  }
  return {
    schema_version: MISSION_SUMMARY_SCHEMA,
    mission_id: stringValue(item.mission_id, "mission_id"),
    request_id: stringValue(item.request_id, "request_id"),
    symbol: stringValue(item.symbol, "symbol"),
    run_mode: enumValue(item.run_mode, RUN_MODES, "run_mode"),
    generated_at: timestamp(item.generated_at, "generated_at"),
    generated_from_snapshot: parseArtifactReference(item.generated_from_snapshot, "generated_from_snapshot"),
    current_phase: enumValue(item.current_phase, CURRENT_PHASES, "current_phase") as CurrentPhase,
    terminal,
    stages,
    modeldock: {
      status: enumValue(modeldock.status, ["NOT_RECORDED", "RUNNING", "SUCCEEDED", "FAILED"] as const, "modeldock.status"),
      provider: nullableString(modeldock.provider, "modeldock.provider"),
      model: nullableString(modeldock.model, "modeldock.model"),
      trace_id: nullableString(modeldock.trace_id, "modeldock.trace_id"),
    },
    governor_disposition: nullableString(item.governor_disposition, "governor_disposition"),
    operator: {
      route: enumOrNull(operator.route, OPERATOR_ROUTES, "operator.route") as OperatorRoute | null,
      action_status: enumValue(operator.action_status, OPERATOR_ACTION_STATUSES, "operator.action_status") as OperatorActionStatus,
      action: enumOrNull(operator.action, OPERATOR_ACTIONS, "operator.action") as OperatorAction | null,
      result: enumOrNull(operator.result, OPERATOR_RESULTS, "operator.result") as OperatorResult | null,
    },
    navigator: {
      technical_status: enumValue(navigator.technical_status, STAGE_STATUSES, "navigator.technical_status") as StageStatus,
      native_state: nullableString(navigator.native_state, "navigator.native_state"),
      mode: enumOrNull(navigator.mode, ["SHADOW"] as const, "navigator.mode"),
      handoff_status: enumOrNull(navigator.handoff_status, ["STAGED"] as const, "navigator.handoff_status"),
      intake_status: enumOrNull(navigator.intake_status, ["ACCEPTED", "REJECTED"] as const, "navigator.intake_status"),
      plan_status: enumOrNull(navigator.plan_status, ["CREATED"] as const, "navigator.plan_status"),
    },
    approval_scope: enumOrNull(item.approval_scope, ["NAVIGATOR_SHADOW_HANDOFF"] as const, "approval_scope"),
    final_outcome: enumValue(item.final_outcome, MISSION_OUTCOMES, "final_outcome") as MissionOutcome,
    important_warnings: warningValues,
    snapshot_count: positiveInteger(item.snapshot_count, "snapshot_count"),
    canonical_snapshot_path: "mission_snapshot.json",
    display_title: stringValue(item.display_title, "display_title"),
    subtitle: stringValue(item.subtitle, "subtitle"),
    ordered_stages: ordered,
    resumable,
    event_count: eventCount,
    artifact_links: artifactLinks as MissionSummaryV2["artifact_links"],
  };
}

function parseLogEntry(value: unknown, label: string): CaptainsLogEntry {
  const item = objectValue(value, label);
  exactKeys(item, ["stage", "timestamp", "status", "summary", "source_artifacts"], label);
  if (!Array.isArray(item.source_artifacts) || item.source_artifacts.length === 0) {
    throw new PresentationContractError(`${label}.source_artifacts must be nonempty`);
  }
  const status = stringValue(item.status, `${label}.status`);
  if (!STATUS_TOKEN.test(status)) throw new PresentationContractError(`${label}.status must be a canonical token`);
  return {
    stage: enumValue(item.stage, PRESENTATION_STAGE_ORDER, `${label}.stage`) as PresentationStage,
    timestamp: timestamp(item.timestamp, `${label}.timestamp`),
    status,
    summary: stringValue(item.summary, `${label}.summary`),
    source_artifacts: item.source_artifacts.map((artifact, index) => parseArtifactReference(artifact, `${label}.source_artifacts[${index}]`)),
  };
}

export function parseCaptainsLog(value: unknown): CaptainsLogV1 {
  const item = objectValue(value, "Captain's Log");
  exactKeys(item, ["schema_version", "mission_id", "request_id", "symbol", "run_mode", "generated_at", "generated_from_snapshot", "entries"], "Captain's Log");
  if (item.schema_version !== CAPTAINS_LOG_SCHEMA) throw new PresentationContractError(`unsupported Captain's Log schema: ${String(item.schema_version)}`);
  if (!Array.isArray(item.entries)) throw new PresentationContractError("Captain's Log entries must be an array");
  const entries = item.entries.map((entry, index) => parseLogEntry(entry, `entries[${index}]`));
  if (entries.map((entry) => entry.stage).join("|") !== PRESENTATION_STAGE_ORDER.join("|")) {
    throw new PresentationContractError("Captain's Log must use canonical stage order");
  }
  return {
    schema_version: CAPTAINS_LOG_SCHEMA,
    mission_id: stringValue(item.mission_id, "mission_id"),
    request_id: stringValue(item.request_id, "request_id"),
    symbol: stringValue(item.symbol, "symbol"),
    run_mode: enumValue(item.run_mode, RUN_MODES, "run_mode") as RunMode,
    generated_at: timestamp(item.generated_at, "generated_at"),
    generated_from_snapshot: parseArtifactReference(item.generated_from_snapshot, "generated_from_snapshot"),
    entries,
  };
}

function assertOperations(actual: string[], expected: readonly string[], label: string): void {
  if (actual.join("|") !== expected.join("|")) {
    throw new PresentationContractError(`${label} must preserve the canonical SHADOW safety policy`);
  }
}

export function parseDemoManifest(value: unknown): DemoManifestV1 {
  const item = objectValue(value, "demo manifest");
  exactKeys(item, [
    "schema_version", "demo_scenario", "mission_id", "symbol", "run_mode", "build_week_revision",
    "battlestar_revision", "modeldock_mode", "modeldock_revision_or_service_identity", "modeldock_provider",
    "modeldock_model", "modeldock_trace_id", "final_outcome", "snapshot_count", "captains_log",
    "mission_summary", "final_snapshot", "generated_at", "shadow_only_declaration", "allowed_operations",
    "prohibited_operations",
  ], "demo manifest");
  if (item.schema_version !== DEMO_MANIFEST_SCHEMA) throw new PresentationContractError(`unsupported demo manifest schema: ${String(item.schema_version)}`);
  const scenario = enumValue(item.demo_scenario, ["approved", "held", "vetoed", "failed", "incomplete"] as const, "demo_scenario");
  const outcome = enumValue(item.final_outcome, MISSION_OUTCOMES, "final_outcome") as MissionOutcome;
  if (scenario.toUpperCase() !== outcome) throw new PresentationContractError("demo scenario and final outcome conflict");
  const allowed = uniqueStrings(stringArray(item.allowed_operations, "allowed_operations"), "allowed_operations");
  const prohibited = uniqueStrings(stringArray(item.prohibited_operations, "prohibited_operations"), "prohibited_operations");
  assertOperations(allowed, NAVIGATOR_ALLOWED_OPERATIONS, "allowed_operations");
  assertOperations(prohibited, NAVIGATOR_PROHIBITED_OPERATIONS, "prohibited_operations");
  if (item.shadow_only_declaration !== "NAVIGATOR_SHADOW_ONLY_NO_EXECUTION") {
    throw new PresentationContractError("demo manifest is missing the SHADOW-only declaration");
  }
  return {
    schema_version: DEMO_MANIFEST_SCHEMA,
    demo_scenario: scenario,
    mission_id: stringValue(item.mission_id, "mission_id"),
    symbol: stringValue(item.symbol, "symbol"),
    run_mode: enumValue(item.run_mode, RUN_MODES, "run_mode") as RunMode,
    build_week_revision: stringValue(item.build_week_revision, "build_week_revision"),
    battlestar_revision: stringValue(item.battlestar_revision, "battlestar_revision"),
    modeldock_mode: enumValue(item.modeldock_mode, MODELDOCK_MODES, "modeldock_mode") as ModelDockDemoMode,
    modeldock_revision_or_service_identity: nullableString(item.modeldock_revision_or_service_identity, "modeldock_revision_or_service_identity"),
    modeldock_provider: nullableString(item.modeldock_provider, "modeldock_provider"),
    modeldock_model: nullableString(item.modeldock_model, "modeldock_model"),
    modeldock_trace_id: nullableString(item.modeldock_trace_id, "modeldock_trace_id"),
    final_outcome: outcome,
    snapshot_count: positiveInteger(item.snapshot_count, "snapshot_count"),
    captains_log: parseArtifactReference(item.captains_log, "captains_log"),
    mission_summary: parseArtifactReference(item.mission_summary, "mission_summary"),
    final_snapshot: parseArtifactReference(item.final_snapshot, "final_snapshot"),
    generated_at: timestamp(item.generated_at, "generated_at"),
    shadow_only_declaration: "NAVIGATOR_SHADOW_ONLY_NO_EXECUTION",
    allowed_operations: allowed,
    prohibited_operations: prohibited,
  };
}

/** Live publications do not impose a demo scenario or an approved-only gate. */
export function parsePresentationManifest(value: unknown): PresentationManifestV1 {
  const item = objectValue(value, "presentation manifest");
  exactKeys(item, [
    "schema_version", "mission_id", "symbol", "run_mode", "build_week_revision",
    "battlestar_revision", "modeldock_mode", "modeldock_revision_or_service_identity", "modeldock_provider",
    "modeldock_model", "modeldock_trace_id", "final_outcome", "snapshot_count", "captains_log",
    "mission_summary", "final_snapshot", "generated_at", "shadow_only_declaration", "allowed_operations",
    "prohibited_operations",
    ...(Object.hasOwn(item, "cabin_context") ? ["cabin_context"] : []),
    ...(Object.hasOwn(item, "navigator_catalog") ? ["navigator_catalog"] : []),
    ...(Object.hasOwn(item, "navigator_fleet_catalog") ? ["navigator_fleet_catalog"] : []),
  ], "presentation manifest");
  if (item.schema_version !== PRESENTATION_MANIFEST_SCHEMA) {
    throw new PresentationContractError("unsupported presentation manifest schema");
  }
  const allowed = uniqueStrings(stringArray(item.allowed_operations, "allowed_operations"), "allowed_operations");
  const prohibited = uniqueStrings(stringArray(item.prohibited_operations, "prohibited_operations"), "prohibited_operations");
  assertOperations(allowed, NAVIGATOR_ALLOWED_OPERATIONS, "allowed_operations");
  assertOperations(prohibited, NAVIGATOR_PROHIBITED_OPERATIONS, "prohibited_operations");
  if (item.shadow_only_declaration !== "NAVIGATOR_SHADOW_ONLY_NO_EXECUTION") {
    throw new PresentationContractError("presentation manifest is missing the SHADOW-only declaration");
  }
  const cabinContext = Object.hasOwn(item, "cabin_context") ? parseArtifactReference(item.cabin_context, "cabin_context") : undefined;
  if (cabinContext && (cabinContext.name !== "cabin_context" || cabinContext.path !== "presentation/cabin_context.json"
    || cabinContext.schema_version !== "blackpod.cabin_context.v1")) {
    throw new PresentationContractError("presentation manifest references noncanonical cabin context");
  }
  const navigatorCatalog = Object.hasOwn(item, "navigator_catalog")
    ? parseArtifactReference(item.navigator_catalog, "navigator_catalog") : undefined;
  if (navigatorCatalog && (item.run_mode !== "LIVE" || !cabinContext
    || navigatorCatalog.name !== "navigator_catalog" || navigatorCatalog.path !== "presentation/navigator_catalog.json"
    || navigatorCatalog.schema_version !== "blackpod.navigator_catalog.v1" || navigatorCatalog.producer !== "harbormaster"
    || navigatorCatalog.byte_size === null || !Number.isSafeInteger(navigatorCatalog.byte_size)
    || navigatorCatalog.observed_at === null)) {
    throw new PresentationContractError("presentation manifest references an inconsistent LIVE Navigator catalog");
  }
  const fleetCatalog = Object.hasOwn(item, "navigator_fleet_catalog")
    ? parseArtifactReference(item.navigator_fleet_catalog, "navigator_fleet_catalog") : undefined;
  if (fleetCatalog && (item.run_mode !== "LIVE" || fleetCatalog.name !== "navigator_fleet_catalog"
    || fleetCatalog.path !== "presentation/navigator_fleet_catalog.json" || fleetCatalog.schema_version !== "blackpod.navigator_fleet_catalog.v1"
    || fleetCatalog.producer !== "harbormaster" || fleetCatalog.byte_size === null || !Number.isSafeInteger(fleetCatalog.byte_size)
    || fleetCatalog.observed_at === null)) {
    throw new PresentationContractError("presentation manifest references an inconsistent LIVE Navigator fleet catalog");
  }
  return {
    schema_version: PRESENTATION_MANIFEST_SCHEMA,
    mission_id: stringValue(item.mission_id, "mission_id"),
    symbol: stringValue(item.symbol, "symbol"),
    run_mode: enumValue(item.run_mode, RUN_MODES, "run_mode"),
    build_week_revision: nullableString(item.build_week_revision, "build_week_revision"),
    battlestar_revision: nullableString(item.battlestar_revision, "battlestar_revision"),
    modeldock_mode: enumValue(item.modeldock_mode, [...MODELDOCK_MODES, "NOT_RECORDED", "RUNNING"] as const, "modeldock_mode"),
    modeldock_revision_or_service_identity: nullableString(item.modeldock_revision_or_service_identity, "modeldock_revision_or_service_identity"),
    modeldock_provider: nullableString(item.modeldock_provider, "modeldock_provider"),
    modeldock_model: nullableString(item.modeldock_model, "modeldock_model"),
    modeldock_trace_id: nullableString(item.modeldock_trace_id, "modeldock_trace_id"),
    final_outcome: enumValue(item.final_outcome, MISSION_OUTCOMES, "final_outcome"),
    snapshot_count: positiveInteger(item.snapshot_count, "snapshot_count"),
    captains_log: parseArtifactReference(item.captains_log, "captains_log"),
    mission_summary: parseArtifactReference(item.mission_summary, "mission_summary"),
    final_snapshot: parseArtifactReference(item.final_snapshot, "final_snapshot"),
    generated_at: timestamp(item.generated_at, "generated_at"),
    shadow_only_declaration: "NAVIGATOR_SHADOW_ONLY_NO_EXECUTION",
    allowed_operations: allowed,
    prohibited_operations: prohibited,
    ...(cabinContext ? { cabin_context: cabinContext } : {}),
    ...(navigatorCatalog ? { navigator_catalog: navigatorCatalog } : {}),
    ...(fleetCatalog ? { navigator_fleet_catalog: fleetCatalog } : {}),
  };
}

export function validateMissionBundleContracts(contracts: PrimaryMissionContracts): PrimaryMissionContracts {
  const { summary, captainsLog, manifest, snapshot } = contracts;
  const identities = [summary, captainsLog, manifest, snapshot];
  for (const contract of identities) {
    if (contract.mission_id !== summary.mission_id || contract.run_mode !== summary.run_mode) {
      throw new PresentationContractError("presentation contracts contain conflicting mission correlation");
    }
  }
  if (captainsLog.request_id !== summary.request_id || snapshot.request_id !== summary.request_id) {
    throw new PresentationContractError("presentation contracts contain conflicting request correlation");
  }
  if (captainsLog.symbol !== summary.symbol || manifest.symbol !== summary.symbol) {
    throw new PresentationContractError("presentation contracts contain conflicting symbols");
  }
  if (manifest.final_outcome !== summary.final_outcome || snapshot.mission_outcome !== summary.final_outcome) {
    throw new PresentationContractError("presentation contracts contain conflicting canonical outcomes");
  }
  if (snapshot.current_phase !== summary.current_phase || snapshot.terminal !== summary.terminal) {
    throw new PresentationContractError("mission summary conflicts with the final snapshot state");
  }
  if (summary.snapshot_count !== manifest.snapshot_count || snapshot.revision !== summary.snapshot_count) {
    throw new PresentationContractError("presentation contracts contain conflicting snapshot counts");
  }
  if (summary.generated_at !== captainsLog.generated_at || summary.generated_at !== manifest.generated_at || summary.generated_at !== snapshot.observed_at) {
    throw new PresentationContractError("presentation contracts contain conflicting generated timestamps");
  }
  if (summary.approval_scope !== snapshot.approval_scope) {
    throw new PresentationContractError("mission summary conflicts with canonical approval scope");
  }
  if (snapshot.navigator.mode === null) {
    // An unstarted canonical Navigator has an empty envelope, not a SHADOW
    // handoff. The publication still declares the product's SHADOW-only limit.
    if (snapshot.navigator.allowed_operations.length || snapshot.navigator.prohibited_operations.length
      || Object.entries(snapshot.navigator).some(([key, value]) => !["allowed_operations", "prohibited_operations"].includes(key) && value !== null)) {
      throw new PresentationContractError("empty Navigator state may not contain SHADOW progress or operations");
    }
  } else {
    assertOperations(snapshot.navigator.allowed_operations, manifest.allowed_operations, "snapshot allowed_operations");
    assertOperations(snapshot.navigator.prohibited_operations, manifest.prohibited_operations, "snapshot prohibited_operations");
  }
  if (manifest.captains_log.path !== "presentation/captains_log.json" || manifest.mission_summary.path !== "presentation/mission_summary.json" || manifest.final_snapshot.path !== "mission_snapshot.json") {
    throw new PresentationContractError("presentation manifest references noncanonical primary paths");
  }
  if (manifest.schema_version === PRESENTATION_MANIFEST_SCHEMA) validateLivePublicationContracts(contracts);
  return contracts;
}

function validateLivePublicationContracts({ summary, captainsLog, manifest, snapshot }: PrimaryMissionContracts): void {
  if (summary.run_mode !== "LIVE" || manifest.modeldock_mode === "REPLAYED") {
    throw new PresentationContractError("live publication may not contain REPLAY evidence");
  }
  for (const [reference, name, schema] of [
    [manifest.captains_log, "captains_log", CAPTAINS_LOG_SCHEMA],
    [manifest.mission_summary, "mission_summary", MISSION_SUMMARY_SCHEMA],
    [manifest.final_snapshot, "mission_snapshot", MISSION_SNAPSHOT_SCHEMA],
  ] as const) {
    if (reference.name !== name || reference.schema_version !== schema || reference.observed_at !== snapshot.observed_at) {
      throw new PresentationContractError("presentation manifest primary reference conflicts with canonical metadata");
    }
  }
  const immutablePath = `snapshots/mission_snapshot-r${String(snapshot.revision).padStart(4, "0")}.json`;
  for (const reference of [summary.generated_from_snapshot, captainsLog.generated_from_snapshot]) {
    if (reference.path !== immutablePath || reference.sha256 !== manifest.final_snapshot.sha256
      || reference.schema_version !== MISSION_SNAPSHOT_SCHEMA
      || reference.observed_at !== snapshot.observed_at) {
      throw new PresentationContractError("generated_from_snapshot must reference the latest immutable snapshot");
    }
  }
  for (const stage of CANONICAL_STAGE_NAMES) {
    if (summary.stages[stage].technical_status !== snapshot.stages[stage].status
      || summary.stages[stage].native_state !== snapshot.stages[stage].native_state) {
      throw new PresentationContractError("mission summary stage conflicts with canonical snapshot");
    }
    for (const call of snapshot.stages[stage].modeldock_calls) {
      if (call.mission_id !== snapshot.mission_id || call.request_id !== snapshot.request_id || call.run_mode !== "LIVE") {
        throw new PresentationContractError("ModelDock call conflicts with LIVE mission correlation");
      }
      if (call.status === "SUCCEEDED" && (call.mocked !== false || call.provider !== "mlx")) {
        throw new PresentationContractError("successful LIVE ModelDock inference requires nonmocked mlx provenance");
      }
    }
  }
  for (const key of ["route", "action_status", "action", "result"] as const) {
    if (summary.operator[key] !== snapshot.operator[key]) {
      throw new PresentationContractError("mission summary operator conflicts with canonical snapshot");
    }
  }
  for (const key of ["mode", "handoff_status", "intake_status", "plan_status"] as const) {
    if (summary.navigator[key] !== snapshot.navigator[key]) {
      throw new PresentationContractError("mission summary Navigator conflicts with canonical snapshot");
    }
  }
  if (summary.navigator.technical_status !== snapshot.stages.navigator.status
    || summary.navigator.native_state !== snapshot.stages.navigator.native_state
    || summary.governor_disposition !== snapshot.stages.governor.native_state) {
    throw new PresentationContractError("mission summary disposition conflicts with canonical snapshot");
  }
  const lastCall = snapshot.stages.oracle.modeldock_calls.at(-1) ?? null;
  if (lastCall?.status === "SUCCEEDED") {
    const component = snapshot.components.modeldock;
    if (!lastCall.model || !lastCall.trace_id || !component
      || component.run_mode !== "LIVE" || component.transport !== "LIVE_HTTP"
      || component.expected_provider !== "mlx" || component.replay_fixture_id !== null
      || component.endpoint !== lastCall.endpoint) {
      throw new PresentationContractError("successful ModelDock inference requires consistent LIVE_HTTP provenance");
    }
  }
  const expectedMode = lastCall?.status === "SUCCEEDED" ? "LIVE" : lastCall?.status ?? "NOT_RECORDED";
  if (manifest.modeldock_mode !== expectedMode || summary.modeldock.status !== (lastCall?.status ?? "NOT_RECORDED")) {
    throw new PresentationContractError("ModelDock presentation state conflicts with recorded inference");
  }
  for (const [summaryKey, manifestKey] of [
    ["provider", "modeldock_provider"], ["model", "modeldock_model"], ["trace_id", "modeldock_trace_id"],
  ] as const) {
    const expected = lastCall?.[summaryKey] ?? null;
    if (summary.modeldock[summaryKey] !== expected || manifest[manifestKey] !== expected) {
      throw new PresentationContractError("ModelDock identity conflicts with recorded inference");
    }
  }
}

export function asJsonObject(value: unknown, label = "artifact"): JsonObject {
  return objectValue(value, label) as JsonObject;
}

export function getObject(value: JsonValue | undefined): JsonObject | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value : undefined;
}

export function getString(value: JsonValue | undefined): string | undefined {
  return typeof value === "string" && value.trim() === value && value.length > 0 ? value : undefined;
}

export function getNumber(value: JsonValue | undefined): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

export function getBoolean(value: JsonValue | undefined): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}

export function getStringArray(value: JsonValue | undefined): string[] | undefined {
  return Array.isArray(value) && value.every((entry) => typeof entry === "string") ? [...value] as string[] : undefined;
}
