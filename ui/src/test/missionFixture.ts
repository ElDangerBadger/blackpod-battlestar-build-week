import {
  CAPTAINS_LOG_SCHEMA,
  DEMO_MANIFEST_SCHEMA,
  MISSION_SNAPSHOT_SCHEMA,
  MISSION_SUMMARY_SCHEMA,
  NAVIGATOR_ALLOWED_OPERATIONS,
  NAVIGATOR_PROHIBITED_OPERATIONS,
  PRESENTATION_STAGE_ORDER,
  type ArtifactReference,
  type CaptainsLogV1,
  type DemoManifestV1,
  type MissionSnapshotV1,
  type MissionSummaryV2,
  type SnapshotStageContract,
} from "../contracts/presentation";
import {
  MISSION_EVIDENCE_NAMES,
  type MissionBundle,
  type MissionEvidence,
} from "../data/loadMission";

const WHEN = "2026-07-18T18:07:00Z";
const HASH = "a".repeat(64);

export function artifact(name: string, path: string, schema: string | null = null): ArtifactReference {
  return {
    name,
    path,
    sha256: HASH,
    producer: "harbormaster",
    byte_size: 10,
    schema_version: schema,
    observed_at: WHEN,
  };
}

const succeeded = (native_state: string): SnapshotStageContract => ({
  status: "SUCCEEDED",
  native_state,
  inputs: [],
  outputs: [],
  error: null,
  modeldock_calls: [],
});

export function createMissionBundleFixture(): MissionBundle {
  const finalSnapshot = artifact("mission_snapshot", "mission_snapshot.json", MISSION_SNAPSHOT_SCHEMA);
  const immutableSnapshot = artifact("mission_snapshot_r0013", "snapshots/mission_snapshot-r0013.json", MISSION_SNAPSHOT_SCHEMA);
  const summary: MissionSummaryV2 = {
    schema_version: MISSION_SUMMARY_SCHEMA,
    mission_id: "mission-buildweek-replay-001",
    request_id: "request-replay-example-001",
    symbol: "AAPL",
    run_mode: "REPLAY",
    generated_at: WHEN,
    generated_from_snapshot: immutableSnapshot,
    current_phase: "COMPLETE",
    terminal: true,
    stages: {
      harbormaster: { technical_status: "SUCCEEDED", native_state: "INITIALIZED" },
      oracle: { technical_status: "SUCCEEDED", native_state: "READY" },
      council: { technical_status: "SUCCEEDED", native_state: "MIXED" },
      governor: { technical_status: "SUCCEEDED", native_state: "PROCEED" },
      navigator: { technical_status: "SUCCEEDED", native_state: "CREATED" },
    },
    modeldock: { status: "SUCCEEDED", provider: "mlx", model: "demo-model", trace_id: "trace-001" },
    governor_disposition: "PROCEED",
    operator: {
      route: "PENDING_APPROVAL",
      action_status: "SUCCEEDED",
      action: "APPROVE_HANDOFF",
      result: "APPROVED_FOR_HANDOFF",
    },
    navigator: {
      technical_status: "SUCCEEDED",
      native_state: "CREATED",
      mode: "SHADOW",
      handoff_status: "STAGED",
      intake_status: "ACCEPTED",
      plan_status: "CREATED",
    },
    approval_scope: "NAVIGATOR_SHADOW_HANDOFF",
    final_outcome: "APPROVED",
    important_warnings: ["MISSING_PRIOR_ORACLE_MEASUREMENTS"],
    snapshot_count: 13,
    canonical_snapshot_path: "mission_snapshot.json",
    display_title: "BlackPod Mission: AAPL",
    subtitle: "REPLAY | APPROVED | COMPLETE",
    ordered_stages: [
      ["HARBORMASTER", "SUCCEEDED", "Mission accepted."],
      ["ORACLE", "SUCCEEDED", "Oracle READY."],
      ["MODELDOCK", "SUCCEEDED", "Narrative validated."],
      ["COUNCIL", "SUCCEEDED", "Council MIXED."],
      ["GOVERNOR", "PROCEED", "Governor PROCEED; this alone is not approval."],
      ["OPERATOR", "APPROVED_FOR_HANDOFF", "Explicit operator approval recorded."],
      ["NAVIGATOR", "SHADOW PLAN CREATED", "SHADOW plan created."],
    ].map(([stage, display_state, stageSummary]) => ({
      stage: stage as MissionSummaryV2["ordered_stages"][number]["stage"],
      display_state,
      summary: stageSummary,
      artifact_paths: ["mission_snapshot.json"],
    })),
    resumable: false,
    event_count: 8,
    artifact_links: {
      captains_log_json: "presentation/captains_log.json",
      captains_log_markdown: "presentation/captains_log.md",
      mission_summary: "presentation/mission_summary.json",
      canonical_snapshot: "mission_snapshot.json",
    },
  };

  const captainsLog: CaptainsLogV1 = {
    schema_version: CAPTAINS_LOG_SCHEMA,
    mission_id: summary.mission_id,
    request_id: summary.request_id,
    symbol: summary.symbol,
    run_mode: summary.run_mode,
    generated_at: WHEN,
    generated_from_snapshot: immutableSnapshot,
    entries: PRESENTATION_STAGE_ORDER.map((stage) => ({
      stage,
      timestamp: WHEN,
      status: stage === "MISSION" ? "APPROVED" : "SUCCEEDED",
      summary: `${stage} canonical event.`,
      source_artifacts: [immutableSnapshot],
    })),
  };

  const manifest: DemoManifestV1 = {
    schema_version: DEMO_MANIFEST_SCHEMA,
    demo_scenario: "approved",
    mission_id: summary.mission_id,
    symbol: summary.symbol,
    run_mode: summary.run_mode,
    build_week_revision: "a".repeat(40),
    battlestar_revision: "b".repeat(40),
    modeldock_mode: "REPLAYED",
    modeldock_revision_or_service_identity: "fixture-modeldock",
    modeldock_provider: "mlx",
    modeldock_model: "demo-model",
    modeldock_trace_id: "trace-001",
    final_outcome: "APPROVED",
    snapshot_count: 13,
    captains_log: artifact("captains_log", "presentation/captains_log.json", CAPTAINS_LOG_SCHEMA),
    mission_summary: artifact("mission_summary", "presentation/mission_summary.json", MISSION_SUMMARY_SCHEMA),
    final_snapshot: finalSnapshot,
    generated_at: WHEN,
    shadow_only_declaration: "NAVIGATOR_SHADOW_ONLY_NO_EXECUTION",
    allowed_operations: [...NAVIGATOR_ALLOWED_OPERATIONS],
    prohibited_operations: [...NAVIGATOR_PROHIBITED_OPERATIONS],
  };

  const snapshot: MissionSnapshotV1 = {
    schema_version: MISSION_SNAPSHOT_SCHEMA,
    snapshot_id: "mission-buildweek-replay-001-r0013",
    mission_id: summary.mission_id,
    request_id: summary.request_id,
    revision: 13,
    previous_snapshot_sha256: "c".repeat(64),
    run_mode: summary.run_mode,
    started_at: WHEN,
    observed_at: WHEN,
    mission_outcome: "APPROVED",
    current_phase: "COMPLETE",
    terminal: true,
    stages: {
      harbormaster: succeeded("INITIALIZED"),
      oracle: succeeded("READY"),
      council: succeeded("MIXED"),
      governor: succeeded("PROCEED"),
      navigator: succeeded("CREATED"),
    },
    artifacts: [],
    components: {},
    operator: {
      route: "PENDING_APPROVAL",
      action_status: "SUCCEEDED",
      action: "APPROVE_HANDOFF",
      result: "APPROVED_FOR_HANDOFF",
      action_id: "operator-action-001",
      operator_id: "demo-operator",
      acted_at: WHEN,
      error: null,
    },
    navigator: {
      mode: "SHADOW",
      handoff_status: "STAGED",
      intake_status: "ACCEPTED",
      plan_status: "CREATED",
      handoff_id: "handoff-001",
      intake_receipt_id: "receipt-001",
      plan_id: "plan-001",
      expires_at: WHEN,
      idempotency_key: "navigator-idempotency-001",
      allowed_operations: [...NAVIGATOR_ALLOWED_OPERATIONS],
      prohibited_operations: [...NAVIGATOR_PROHIBITED_OPERATIONS],
    },
    approval_scope: "NAVIGATOR_SHADOW_HANDOFF",
  };

  const missingEvidence = MISSION_EVIDENCE_NAMES.map((name): [typeof name, MissionEvidence] => [name, {
    name,
    reference: null,
    document: null,
    status: "NOT_REFERENCED",
    message: "Not present in this mission artifact.",
  }]);

  return {
    baseUrl: "./demo/approved/",
    summary,
    captainsLog,
    manifest,
    snapshot,
    artifactIndex: new Map(),
    evidence: new Map(missingEvidence),
  };
}

