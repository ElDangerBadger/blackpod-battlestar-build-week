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
  NavigatorMarket,
  PortfolioSnapshotV1,
} from "../contracts/cabinContext";
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
  startedAt: string;
  observedAt: string;
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
  modelRevision: string | null;
  endpoint: string | null;
  mocked: boolean | null;
  latencyMs: number | null;
  lastSuccessfulInference: string | null;
  availability: string;
  roleStatement: string;
}

export interface MarketContextViewModel {
  status: "CAPTURED" | "NOT_CONFIGURED";
  companyName: string | null;
  category: string | null;
  timeframe: string | null;
  currency: string | null;
  latestCompletedBar: string | null;
  marketStatus: string | null;
  sourceIdentity: string | null;
  capturedAt: string | null;
  regime: string | null;
  navigatorMarket: NavigatorMarket | null;
}

export interface PortfolioViewModel {
  status: "CAPTURED" | "NOT_CONFIGURED";
  mode: string | null;
  sourceIdentity: string | null;
  capturedAt: string | null;
  accountType: string | null;
  currency: string | null;
  positionCount: number;
  activeExposure: ActivePortfolioExposureViewModel;
  snapshot: PortfolioSnapshotV1 | null;
}

export interface ActivePortfolioExposureViewModel {
  status: "NOT_CONFIGURED" | "NO_POSITION" | "POSITION";
  symbol: string;
  direction: "LONG" | "SHORT" | "FLAT" | null;
  quantity: number | null;
  marketValue: number | null;
  allocationPercent: number | null;
  costBasis: number | null;
  unrealizedPnl: number | null;
  cash: number | null;
  equity: number | null;
  totalExposure: number | null;
  currency: string | null;
  capturedAt: string | null;
  mode: string | null;
  sourceIdentity: string | null;
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
  market: MarketContextViewModel;
  portfolio: PortfolioViewModel;
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

function activePortfolioExposure(
  portfolio: PortfolioSnapshotV1 | null,
  symbol: string,
): ActivePortfolioExposureViewModel {
  const position = portfolio?.positions.find((candidate) => candidate.symbol === symbol) ?? null;
  const quantity = position?.quantity ?? null;
  const direction = quantity === null
    ? null
    : quantity > 0
      ? "LONG"
      : quantity < 0
        ? "SHORT"
        : "FLAT";

  return {
    status: portfolio === null ? "NOT_CONFIGURED" : position === null ? "NO_POSITION" : "POSITION",
    symbol,
    direction,
    quantity,
    marketValue: position?.market_value ?? null,
    allocationPercent: position?.allocation_percent ?? null,
    costBasis: position?.cost_basis ?? null,
    unrealizedPnl: position?.unrealized_pnl ?? null,
    cash: portfolio?.cash ?? null,
    equity: portfolio?.equity ?? null,
    totalExposure: portfolio?.total_exposure ?? null,
    currency: portfolio?.currency ?? null,
    capturedAt: portfolio?.captured_at ?? null,
    mode: portfolio?.mode ?? null,
    sourceIdentity: portfolio?.source_identity ?? null,
  };
}

export function createMissionViewModel(bundle: MissionBundle): MissionViewModel {
  const summary = bundle.summary;
  const manifest = bundle.manifest;
  const stages = Object.fromEntries(
    STAGE_BOOK_ORDER.map((id) => [id, stageSummary(bundle, id)]),
  ) as Record<StageBookId, StageBookSummaryViewModel>;
  const modeldockCall = bundle.snapshot.stages.oracle.modeldock_calls.at(-1) ?? null;
  const marketCapture = bundle.cabinContext?.capture_provenance.market ?? null;
  const portfolioCapture = bundle.cabinContext?.capture_provenance.portfolio ?? null;
  const latestMarketPoint = bundle.navigatorMarket?.points.at(-1) ?? null;

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
      startedAt: bundle.snapshot.started_at,
      observedAt: bundle.snapshot.observed_at,
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
      modelRevision: modeldockCall?.model_revision ?? null,
      endpoint: modeldockCall?.endpoint ?? null,
      mocked: modeldockCall?.mocked ?? null,
      latencyMs: modeldockCall?.latency_ms ?? null,
      lastSuccessfulInference: modeldockCall?.status === "SUCCEEDED" ? modeldockCall.observed_at : null,
      availability: modeldockAvailability(
        manifest.modeldock_mode,
        modeldockCall?.status ?? summary.modeldock.status,
        modeldockCall?.mocked ?? null,
        modeldockCall?.provider ?? summary.modeldock.provider,
      ),
      roleStatement: "Narrative only. Oracle remains authoritative for facts, measurements, diagnostics, and readiness.",
    },
    market: {
      status: bundle.navigatorMarket === null ? "NOT_CONFIGURED" : "CAPTURED",
      companyName: bundle.navigatorMarket?.name ?? null,
      category: bundle.navigatorMarket?.category ?? null,
      timeframe: bundle.navigatorMarket?.timeframe ?? null,
      currency: bundle.navigatorMarket?.currency ?? null,
      latestCompletedBar: latestMarketPoint === null ? null : unixSecondsToIso(latestMarketPoint.t),
      marketStatus: null,
      sourceIdentity: marketCapture?.source_identity ?? null,
      capturedAt: bundle.cabinContext?.captured_at ?? null,
      // Cabin supplements do not currently carry a security-specific regime.
      // Fleet-level Oracle posture must not be relabeled as ticker evidence.
      regime: null,
      navigatorMarket: bundle.navigatorMarket,
    },
    portfolio: {
      status: bundle.portfolio === null ? "NOT_CONFIGURED" : "CAPTURED",
      mode: bundle.portfolio?.mode ?? null,
      sourceIdentity: portfolioCapture?.source_identity ?? bundle.portfolio?.source_identity ?? null,
      capturedAt: bundle.portfolio?.captured_at ?? null,
      accountType: bundle.portfolio?.account_type ?? null,
      currency: bundle.portfolio?.currency ?? null,
      positionCount: bundle.portfolio?.positions.length ?? 0,
      activeExposure: activePortfolioExposure(bundle.portfolio, summary.symbol),
      snapshot: bundle.portfolio,
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

function unixSecondsToIso(value: number): string | null {
  const date = new Date(value * 1000);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function modeldockAvailability(mode: string, status: string, mocked: boolean | null, provider: string | null): string {
  if (status !== "SUCCEEDED") return "INFERENCE NOT VERIFIED";
  if (mode === "LIVE" && mocked === false && provider === "mlx") return "LOCAL INFERENCE VERIFIED AT MISSION TIME";
  if (mode === "REPLAYED") return "FROZEN INFERENCE PROVENANCE";
  return "RECORDED INFERENCE VERIFIED";
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
