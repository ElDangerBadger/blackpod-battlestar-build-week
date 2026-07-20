/**
 * Read-only TypeScript projections of the canonical Build Week presentation
 * contracts. These types describe data; they do not derive mission outcomes.
 */

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];
export type JsonObject = { [key: string]: JsonValue };

export const MISSION_SUMMARY_SCHEMA = "blackpod.mission_summary.v2" as const;
export const CAPTAINS_LOG_SCHEMA = "blackpod.captains_log.v1" as const;
export const DEMO_MANIFEST_SCHEMA = "blackpod.demo_manifest.v1" as const;
export const MISSION_SNAPSHOT_SCHEMA = "blackpod.mission_snapshot.v1" as const;

export const PRESENTATION_STAGE_ORDER = [
  "HARBORMASTER",
  "ORACLE",
  "MODELDOCK",
  "COUNCIL",
  "GOVERNOR",
  "OPERATOR",
  "NAVIGATOR",
  "MISSION",
] as const;

export const COMPONENT_STAGE_ORDER = [
  "HARBORMASTER",
  "ORACLE",
  "MODELDOCK",
  "COUNCIL",
  "GOVERNOR",
  "OPERATOR",
  "NAVIGATOR",
] as const;

export const CANONICAL_STAGE_NAMES = [
  "harbormaster",
  "oracle",
  "council",
  "governor",
  "navigator",
] as const;

export const NAVIGATOR_ALLOWED_OPERATIONS = ["VALIDATE", "PLAN_ONLY"] as const;
export const NAVIGATOR_PROHIBITED_OPERATIONS = [
  "SUBMIT_ORDER",
  "CANCEL_ORDER",
  "MODIFY_PORTFOLIO",
  "BROKER_CALL",
] as const;

export type PresentationStage = (typeof PRESENTATION_STAGE_ORDER)[number];
export type ComponentPresentationStage = (typeof COMPONENT_STAGE_ORDER)[number];
export type CanonicalStageName = (typeof CANONICAL_STAGE_NAMES)[number];
export type RunMode = "LIVE" | "REPLAY";
export type MissionOutcome = "APPROVED" | "HELD" | "VETOED" | "FAILED" | "INCOMPLETE";
export type CurrentPhase =
  | "HARBORMASTER"
  | "ORACLE"
  | "COUNCIL"
  | "GOVERNOR"
  | "OPERATOR"
  | "NAVIGATOR"
  | "COMPLETE";
export type StageStatus = "NOT_STARTED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "SKIPPED";
export type OperatorRoute =
  | "PENDING_APPROVAL"
  | "PENDING_REVIEW"
  | "CLOSED_BLOCKED"
  | "CLOSED_NO_ACTION";
export type OperatorActionStatus = "NOT_STARTED" | "RUNNING" | "SUCCEEDED" | "FAILED";
export type OperatorAction = "APPROVE_HANDOFF" | "REJECT";
export type OperatorResult = "APPROVED_FOR_HANDOFF" | "REJECTED";
export type NavigatorMode = "SHADOW";
export type ApprovalScope = "NAVIGATOR_SHADOW_HANDOFF";
export type ModelDockDemoMode = "REPLAYED" | "LIVE" | "DISABLED" | "FAILED";

export interface ArtifactReference {
  name: string;
  path: string;
  sha256: string;
  producer: string | null;
  byte_size: number | null;
  schema_version: string | null;
  observed_at: string | null;
}

export interface PresentationStageState {
  technical_status: StageStatus;
  native_state: string | null;
}

export interface OrderedPresentationStage {
  stage: ComponentPresentationStage;
  display_state: string;
  summary: string;
  artifact_paths: string[];
}

export interface ModelDockPresentationState {
  status: "NOT_RECORDED" | "RUNNING" | "SUCCEEDED" | "FAILED";
  provider: string | null;
  model: string | null;
  trace_id: string | null;
}

export interface OperatorPresentationState {
  route: OperatorRoute | null;
  action_status: OperatorActionStatus;
  action: OperatorAction | null;
  result: OperatorResult | null;
}

export interface NavigatorPresentationState {
  technical_status: StageStatus;
  native_state: string | null;
  mode: NavigatorMode | null;
  handoff_status: "STAGED" | null;
  intake_status: "ACCEPTED" | "REJECTED" | null;
  plan_status: "CREATED" | null;
}

export interface MissionSummaryV2 {
  schema_version: typeof MISSION_SUMMARY_SCHEMA;
  mission_id: string;
  request_id: string;
  symbol: string;
  run_mode: RunMode;
  generated_at: string;
  generated_from_snapshot: ArtifactReference;
  current_phase: CurrentPhase;
  terminal: boolean;
  stages: Record<CanonicalStageName, PresentationStageState>;
  modeldock: ModelDockPresentationState;
  governor_disposition: string | null;
  operator: OperatorPresentationState;
  navigator: NavigatorPresentationState;
  approval_scope: ApprovalScope | null;
  final_outcome: MissionOutcome;
  important_warnings: string[];
  snapshot_count: number;
  canonical_snapshot_path: "mission_snapshot.json";
  display_title: string;
  subtitle: string;
  ordered_stages: OrderedPresentationStage[];
  resumable: boolean;
  event_count: number;
  artifact_links: {
    captains_log_json: "presentation/captains_log.json";
    captains_log_markdown: "presentation/captains_log.md";
    mission_summary: "presentation/mission_summary.json";
    canonical_snapshot: "mission_snapshot.json";
  };
}

export interface CaptainsLogEntry {
  stage: PresentationStage;
  timestamp: string;
  status: string;
  summary: string;
  source_artifacts: ArtifactReference[];
}

export interface CaptainsLogV1 {
  schema_version: typeof CAPTAINS_LOG_SCHEMA;
  mission_id: string;
  request_id: string;
  symbol: string;
  run_mode: RunMode;
  generated_at: string;
  generated_from_snapshot: ArtifactReference;
  entries: CaptainsLogEntry[];
}

export interface DemoManifestV1 {
  schema_version: typeof DEMO_MANIFEST_SCHEMA;
  demo_scenario: "approved" | "held" | "vetoed" | "failed" | "incomplete";
  mission_id: string;
  symbol: string;
  run_mode: RunMode;
  build_week_revision: string;
  battlestar_revision: string;
  modeldock_mode: ModelDockDemoMode;
  modeldock_revision_or_service_identity: string | null;
  modeldock_provider: string | null;
  modeldock_model: string | null;
  modeldock_trace_id: string | null;
  final_outcome: MissionOutcome;
  snapshot_count: number;
  captains_log: ArtifactReference;
  mission_summary: ArtifactReference;
  final_snapshot: ArtifactReference;
  generated_at: string;
  shadow_only_declaration: "NAVIGATOR_SHADOW_ONLY_NO_EXECUTION";
  allowed_operations: string[];
  prohibited_operations: string[];
}

export interface StageErrorContract {
  code: string;
  error_type: string;
  message: string;
  resumable: boolean;
  observed_at: string;
}

export interface ModelDockCallContract {
  call_id: string;
  status: "RUNNING" | "SUCCEEDED" | "FAILED";
  mission_id: string;
  request_id: string;
  run_mode: RunMode;
  endpoint: string;
  provider: string | null;
  model: string | null;
  model_revision: string | null;
  trace_id: string | null;
  mocked: boolean | null;
  latency_ms: number | null;
  request_sha256: string;
  response_sha256: string | null;
  response_byte_size: number | null;
  started_at: string;
  observed_at: string;
  artifacts: string[];
  error: StageErrorContract | null;
}

export interface SnapshotStageContract {
  status: StageStatus;
  native_state: string | null;
  inputs: string[];
  outputs: string[];
  error: StageErrorContract | null;
  modeldock_calls: ModelDockCallContract[];
}

export interface SnapshotOperatorContract {
  route: OperatorRoute | null;
  action_status: OperatorActionStatus;
  action: OperatorAction | null;
  result: OperatorResult | null;
  action_id: string | null;
  operator_id: string | null;
  acted_at: string | null;
  error: StageErrorContract | null;
}

export interface SnapshotNavigatorContract {
  mode: NavigatorMode | null;
  handoff_status: "STAGED" | null;
  intake_status: "ACCEPTED" | "REJECTED" | null;
  plan_status: "CREATED" | null;
  handoff_id: string | null;
  intake_receipt_id: string | null;
  plan_id: string | null;
  expires_at: string | null;
  idempotency_key: string | null;
  allowed_operations: string[];
  prohibited_operations: string[];
}

export interface MissionSnapshotV1 {
  schema_version: typeof MISSION_SNAPSHOT_SCHEMA;
  snapshot_id: string;
  mission_id: string;
  request_id: string;
  revision: number;
  previous_snapshot_sha256: string | null;
  run_mode: RunMode;
  started_at: string;
  observed_at: string;
  mission_outcome: MissionOutcome;
  current_phase: CurrentPhase;
  terminal: boolean;
  stages: Record<CanonicalStageName, SnapshotStageContract>;
  artifacts: ArtifactReference[];
  components: Record<string, JsonObject>;
  operator: SnapshotOperatorContract;
  navigator: SnapshotNavigatorContract;
  approval_scope: ApprovalScope | null;
}
