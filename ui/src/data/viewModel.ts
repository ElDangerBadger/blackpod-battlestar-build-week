import type {
  ArtifactReference,
  CanonicalStageName,
  JsonObject,
  MissionOutcome,
  PresentationStage,
  RunMode,
  StageStatus,
} from "../contracts/presentation";
import type {
  MissionBundle,
  MissionEvidence,
  MissionEvidenceName,
} from "./loadMission";
import { missionRelativeUrl } from "./loadMission";

export type StageBookId = "harbormaster" | "oracle" | "council" | "governor" | "navigator";

export const STAGE_BOOK_ORDER: readonly StageBookId[] = [
  "harbormaster",
  "oracle",
  "council",
  "governor",
  "navigator",
] as const;

export interface MissionStatusViewModel {
  missionId: string;
  requestId: string;
  symbol: string;
  runMode: RunMode;
  outcome: MissionOutcome;
  currentPhase: string;
  generatedAt: string;
  terminal: boolean;
  resumable: boolean;
  snapshotCount: number;
  approvalScope: string | null;
  governorDisposition: string | null;
  operatorRoute: string | null;
  operatorResult: string | null;
  navigatorMode: string | null;
  navigatorHandoffStatus: string | null;
  navigatorIntakeStatus: string | null;
  navigatorPlanStatus: string | null;
  finalSnapshotSha256: string;
}

export interface StageBookSummaryViewModel {
  id: StageBookId;
  title: string;
  technicalStatus: StageStatus;
  nativeState: string | null;
  displayState: string;
  summary: string;
  artifactPaths: readonly string[];
}

export interface CaptainLogEntryViewModel {
  stage: PresentationStage;
  timestamp: string;
  status: string;
  summary: string;
  evidenceCount: number;
  sourceArtifacts: readonly ArtifactReference[];
}

export interface ModelDockViewModel {
  status: string;
  mode: string;
  provider: string | null;
  model: string | null;
  traceId: string | null;
  serviceIdentity: string | null;
  roleStatement: string;
}

export interface SafetyBoundaryViewModel {
  declaration: string;
  displayStatement: string;
  allowedOperations: readonly string[];
  prohibitedOperations: readonly string[];
}

export interface RevisionViewModel {
  buildWeek: string;
  battlestar: string;
  modeldock: string | null;
}

export interface MissionViewModel {
  title: string;
  subtitle: string;
  status: MissionStatusViewModel;
  stages: Record<StageBookId, StageBookSummaryViewModel>;
  captainsLog: readonly CaptainLogEntryViewModel[];
  modeldock: ModelDockViewModel;
  safety: SafetyBoundaryViewModel;
  warnings: readonly string[];
  revisions: RevisionViewModel;
  eventCount: number;
  artifactIndex: ReadonlyMap<string, ArtifactReference>;
  evidence: ReadonlyMap<MissionEvidenceName, MissionEvidence>;
  baseUrl: string;
  components: Readonly<Record<string, JsonObject>>;
}

const TITLES: Record<StageBookId, string> = {
  harbormaster: "Harbormaster",
  oracle: "Oracle",
  council: "Council",
  governor: "Governor",
  navigator: "Navigator",
};

function orderedSummary(bundle: MissionBundle, id: StageBookId) {
  const stageName = id.toUpperCase();
  const value = bundle.summary.ordered_stages.find((stage) => stage.stage === stageName);
  if (value === undefined) {
    throw new Error(`canonical presentation stage ${stageName} is absent`);
  }
  return value;
}

function stageSummary(bundle: MissionBundle, id: StageBookId): StageBookSummaryViewModel {
  const stage = bundle.summary.stages[id as CanonicalStageName];
  const ordered = orderedSummary(bundle, id);
  return {
    id,
    title: TITLES[id],
    technicalStatus: stage.technical_status,
    nativeState: stage.native_state,
    displayState: ordered.display_state,
    summary: ordered.summary,
    artifactPaths: ordered.artifact_paths,
  };
}

export function createMissionViewModel(bundle: MissionBundle): MissionViewModel {
  const summary = bundle.summary;
  const manifest = bundle.manifest;
  const stages = Object.fromEntries(
    STAGE_BOOK_ORDER.map((id) => [id, stageSummary(bundle, id)]),
  ) as Record<StageBookId, StageBookSummaryViewModel>;

  return {
    title: summary.display_title,
    subtitle: summary.subtitle,
    status: {
      missionId: summary.mission_id,
      requestId: summary.request_id,
      symbol: summary.symbol,
      runMode: summary.run_mode,
      outcome: summary.final_outcome,
      currentPhase: summary.current_phase,
      generatedAt: summary.generated_at,
      terminal: summary.terminal,
      resumable: summary.resumable,
      snapshotCount: summary.snapshot_count,
      approvalScope: summary.approval_scope,
      governorDisposition: summary.governor_disposition,
      operatorRoute: summary.operator.route,
      operatorResult: summary.operator.result,
      navigatorMode: summary.navigator.mode,
      navigatorHandoffStatus: summary.navigator.handoff_status,
      navigatorIntakeStatus: summary.navigator.intake_status,
      navigatorPlanStatus: summary.navigator.plan_status,
      finalSnapshotSha256: manifest.final_snapshot.sha256,
    },
    stages,
    captainsLog: bundle.captainsLog.entries.map((entry) => ({
      stage: entry.stage,
      timestamp: entry.timestamp,
      status: entry.status,
      summary: entry.summary,
      evidenceCount: entry.source_artifacts.length,
      sourceArtifacts: entry.source_artifacts,
    })),
    modeldock: {
      status: summary.modeldock.status,
      mode: manifest.modeldock_mode,
      provider: summary.modeldock.provider,
      model: summary.modeldock.model,
      traceId: summary.modeldock.trace_id,
      serviceIdentity: manifest.modeldock_revision_or_service_identity,
      roleStatement: "Narrative only. Oracle remains authoritative for facts, measurements, diagnostics, and readiness.",
    },
    safety: {
      declaration: manifest.shadow_only_declaration,
      displayStatement: "Navigator SHADOW handoff only — no trade or order execution.",
      allowedOperations: manifest.allowed_operations,
      prohibitedOperations: manifest.prohibited_operations,
    },
    warnings: summary.important_warnings,
    revisions: {
      buildWeek: manifest.build_week_revision,
      battlestar: manifest.battlestar_revision,
      modeldock: manifest.modeldock_revision_or_service_identity,
    },
    eventCount: summary.event_count,
    artifactIndex: bundle.artifactIndex,
    evidence: bundle.evidence,
    baseUrl: bundle.baseUrl,
    components: bundle.snapshot.components,
  };
}

export function getEvidence(viewModel: MissionViewModel, name: MissionEvidenceName): MissionEvidence | undefined {
  return viewModel.evidence.get(name);
}

export function getEvidenceDocument(viewModel: MissionViewModel, name: MissionEvidenceName): JsonObject | undefined {
  return getEvidence(viewModel, name)?.document ?? undefined;
}

export function artifactHref(viewModel: MissionViewModel, path: string): string {
  return missionRelativeUrl(viewModel.baseUrl, path);
}
