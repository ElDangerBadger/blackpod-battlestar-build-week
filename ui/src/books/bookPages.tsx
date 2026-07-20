import type { ReactNode } from "react";
import type { JsonObject, JsonValue } from "../contracts/presentation";
import type { MissionEvidenceName } from "../data/loadMission";
import {
  getBoolean,
  getNumber,
  getObject,
  getString,
  getStringArray,
} from "../data/validate";
import {
  getEvidence,
  getEvidenceDocument,
  type MissionViewModel,
  type StageBookId,
} from "../data/viewModel";

export type { StageBookId } from "../data/viewModel";

export interface BookPage {
  id: string;
  title: string;
  eyebrow?: string;
  content: ReactNode;
  evidencePaths?: readonly string[];
}

export interface BookDefinition {
  id: StageBookId;
  title: string;
  subtitle: string;
  state: string;
  deskLines: readonly string[];
  pages: readonly BookPage[];
  accent: string;
}

const NOT_PRESENT = "Not present in this mission artifact.";

function scalar(value: JsonValue | undefined): string | undefined {
  if (typeof value === "string" && value.length > 0) return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return undefined;
}

function field(document: JsonObject | undefined, key: string): string {
  return scalar(document?.[key]) ?? NOT_PRESENT;
}

function list(document: JsonObject | undefined, key: string): readonly string[] {
  return getStringArray(document?.[key]) ?? [];
}

function evidencePaths(viewModel: MissionViewModel, names: readonly MissionEvidenceName[]): readonly string[] {
  return names.flatMap((name) => {
    const reference = getEvidence(viewModel, name)?.reference;
    return reference === null || reference === undefined ? [] : [reference.path];
  });
}

function FieldList({ rows }: { rows: readonly [string, string | undefined][] }) {
  return (
    <dl className="book-fields">
      {rows.map(([label, value]) => (
        <div className="book-field" key={label}>
          <dt>{label}</dt>
          <dd>{value ?? NOT_PRESENT}</dd>
        </div>
      ))}
    </dl>
  );
}

function BulletList({ values, empty = NOT_PRESENT }: { values: readonly string[]; empty?: string }) {
  if (values.length === 0) return <p className="book-empty">{empty}</p>;
  return <ul>{values.map((value, index) => <li key={`${index}-${value}`}>{value}</li>)}</ul>;
}

function EvidenceState({ viewModel, name }: { viewModel: MissionViewModel; name: MissionEvidenceName }) {
  const evidence = getEvidence(viewModel, name);
  if (evidence?.status === "LOADED") return null;
  return <p className="book-empty">{evidence?.message ?? NOT_PRESENT}</p>;
}

function requestPages(viewModel: MissionViewModel): BookPage[] {
  const request = getEvidenceDocument(viewModel, "mission_request");
  const snapshot = viewModel.status;
  const battlestar = viewModel.components.battlestar;
  const council = viewModel.components.battlestar_council;
  const governor = viewModel.components.battlestar_governor;
  const modeldock = viewModel.components.modeldock;
  const requestEvidence = evidencePaths(viewModel, ["mission_request"]);
  return [
    {
      id: "harbormaster-request",
      title: "Mission request",
      eyebrow: "Accepted input",
      content: <>
        <EvidenceState viewModel={viewModel} name="mission_request" />
        <FieldList rows={[
          ["Symbol", getString(request?.symbol)],
          ["Run mode", getString(request?.run_mode)],
          ["Requested at", getString(request?.requested_at)],
          ["Request operator", getString(request?.operator_id)],
          ["Schema", getString(request?.schema_version)],
        ]} />
        <p className="book-note">The request operator identifies mission submission; it does not imply operator handoff approval.</p>
      </>,
      evidencePaths: requestEvidence,
    },
    {
      id: "harbormaster-identity",
      title: "Mission identity and correlation",
      eyebrow: "Canonical identifiers",
      content: <FieldList rows={[
        ["Mission ID", snapshot.missionId],
        ["Request ID", snapshot.requestId],
        ["Symbol", snapshot.symbol],
        ["Run mode", snapshot.runMode],
        ["Started at", field(request, "requested_at")],
      ]} />,
      evidencePaths: requestEvidence,
    },
    {
      id: "harbormaster-integrity",
      title: "Artifact integrity and snapshots",
      eyebrow: "Immutable record",
      content: <FieldList rows={[
        ["Snapshot count", String(snapshot.snapshotCount)],
        ["Final snapshot SHA-256", viewModel.status.finalSnapshotSha256],
        ["Indexed artifacts", String(viewModel.artifactIndex.size)],
        ["Terminal", snapshot.terminal ? "Yes" : "No"],
        ["Resumable", snapshot.resumable ? "Yes" : "No"],
      ]} />,
      evidencePaths: ["mission_snapshot.json"],
    },
    {
      id: "harbormaster-revisions",
      title: "Component revisions",
      eyebrow: "Recorded provenance",
      content: <>
        <FieldList rows={[
          ["Build Week", viewModel.revisions.buildWeek],
          ["Battlestar", viewModel.revisions.battlestar],
          ["Battlestar branch", getString(battlestar?.git_branch)],
          ["Battlestar dirty", getBoolean(battlestar?.dirty_worktree) === undefined ? undefined : getBoolean(battlestar?.dirty_worktree) ? "Yes" : "No"],
          ["Oracle transport", getString(battlestar?.transport)],
          ["Council transport", getString(council?.transport)],
          ["Governor transport", getString(governor?.transport)],
          ["ModelDock transport", getString(modeldock?.transport)],
          ["ModelDock identity", viewModel.revisions.modeldock ?? undefined],
        ]} />
        <p className="book-note">Only recorded revisions and service identities are shown.</p>
      </>,
      evidencePaths: ["mission_snapshot.json", "presentation/demo_manifest.json"],
    },
  ];
}

function oraclePages(viewModel: MissionViewModel): BookPage[] {
  const report = getEvidenceDocument(viewModel, "oracle_report");
  const measurements = getEvidenceDocument(viewModel, "oracle_measurements");
  const diagnostics = getEvidenceDocument(viewModel, "oracle_measurement_diagnostics");
  const readiness = getEvidenceDocument(viewModel, "oracle_readiness_report");
  const assessment = getEvidenceDocument(viewModel, "oracle_assessment");
  const oracleNarrative = getEvidenceDocument(viewModel, "oracle_narrative");
  const modeldockNarrative = getEvidenceDocument(viewModel, "oracle_modeldock_narrative");
  const modeldockProvenance = getEvidenceDocument(viewModel, "oracle_modeldock_provenance");
  const reportEvidence = evidencePaths(viewModel, ["oracle_report", "oracle_assessment", "oracle_narrative"]);
  return [
    {
      id: "oracle-assessment",
      title: "Executive assessment",
      eyebrow: "Oracle authority",
      content: <>
        <EvidenceState viewModel={viewModel} name="oracle_report" />
        <p className="book-lede">{field(report, "headline")}</p>
        <p>{field(report, "summary")}</p>
        <FieldList rows={[
          ["Native state", viewModel.stages.oracle.nativeState ?? undefined],
          ["Breadth", getString(assessment?.breadth_posture)],
          ["Leadership", getString(assessment?.leadership_posture)],
          ["Rotation", getString(assessment?.rotation_posture)],
          ["Risk regime", getString(assessment?.risk_regime_posture)],
          ["Assessment confidence", getNumber(assessment?.confidence)?.toString()],
        ]} />
      </>,
      evidencePaths: reportEvidence,
    },
    {
      id: "oracle-measurements",
      title: "Measurements and signals",
      eyebrow: "Validated fleet measurements",
      content: <>
        <EvidenceState viewModel={viewModel} name="oracle_measurements" />
        <FieldList rows={[
          ["Breadth score", getNumber(measurements?.breadth_score)?.toString()],
          ["Risk-on score", getNumber(measurements?.risk_on_score)?.toString()],
          ["Risk-off score", getNumber(measurements?.risk_off_score)?.toString()],
          ["Cyclical strength", getNumber(measurements?.cyclical_strength)?.toString()],
          ["Defensive strength", getNumber(measurements?.defensive_strength)?.toString()],
          ["Leadership concentration", getNumber(measurements?.leadership_concentration)?.toString()],
          ["Rotation velocity", getNumber(measurements?.rotation_velocity)?.toString()],
          ["Sector dispersion", getNumber(measurements?.sector_dispersion)?.toString()],
        ]} />
        <p className="book-note">These are validation-fleet measurements, not security-specific trade signals.</p>
      </>,
      evidencePaths: evidencePaths(viewModel, ["oracle_measurements"]),
    },
    {
      id: "oracle-diagnostics",
      title: "Diagnostics and readiness",
      eyebrow: "Technical evidence",
      content: <>
        <FieldList rows={[
          ["Diagnostics state", getString(diagnostics?.diagnostics_state)],
          ["Diagnostics summary", getString(diagnostics?.summary)],
          ["Symbols used", getNumber(diagnostics?.symbols_used_count)?.toString()],
          ["Symbols missing", getNumber(diagnostics?.symbols_missing_count)?.toString()],
          ["Symbols excluded", getNumber(diagnostics?.symbols_excluded_count)?.toString()],
          ["Fallback count", getNumber(diagnostics?.fallback_count)?.toString()],
          ["Readiness", getString(readiness?.readiness_state)],
          ["Downstream ready", getBoolean(readiness?.downstream_ready) === undefined ? undefined : getBoolean(readiness?.downstream_ready) ? "Yes" : "No"],
          ["Freshness", getBoolean(readiness?.freshness_ok) === undefined ? undefined : getBoolean(readiness?.freshness_ok) ? "Pass" : "Fail"],
          ["Coverage", getBoolean(readiness?.coverage_ok) === undefined ? undefined : getBoolean(readiness?.coverage_ok) ? "Pass" : "Fail"],
        ]} />
      </>,
      evidencePaths: evidencePaths(viewModel, ["oracle_measurement_diagnostics", "oracle_readiness_report"]),
    },
    {
      id: "oracle-modeldock",
      title: "ModelDock narrative",
      eyebrow: "Narrative enrichment only",
      content: <>
        <EvidenceState viewModel={viewModel} name="oracle_modeldock_narrative" />
        <p className="book-lede">{field(modeldockNarrative, "summary")}</p>
        <FieldList rows={[
          ["Status", viewModel.modeldock.status],
          ["Mode", viewModel.modeldock.mode],
          ["Provider", viewModel.modeldock.provider ?? undefined],
          ["Model", viewModel.modeldock.model ?? undefined],
          ["Trace ID", viewModel.modeldock.traceId ?? undefined],
          ["Interpretation", getString(modeldockNarrative?.interpretation)],
          ["Confidence explanation", getString(modeldockNarrative?.confidence_explanation)],
        ]} />
        <p className="book-note">{viewModel.modeldock.roleStatement}</p>
      </>,
      evidencePaths: evidencePaths(viewModel, ["oracle_modeldock_narrative", "oracle_modeldock_provenance"]),
    },
    {
      id: "oracle-warnings",
      title: "Warnings and uncertainty",
      eyebrow: "Preserved without reinterpretation",
      content: <>
        <h3>Oracle warnings</h3>
        <BulletList values={list(report, "warnings")} />
        <h3>ModelDock uncertainties</h3>
        <BulletList values={list(modeldockNarrative, "uncertainties")} />
        <h3>ModelDock warnings</h3>
        <BulletList values={list(modeldockNarrative, "warnings")} />
      </>,
      evidencePaths: evidencePaths(viewModel, ["oracle_report", "oracle_modeldock_narrative"]),
    },
    {
      id: "oracle-provenance",
      title: "Provenance and evidence",
      eyebrow: "Correlated sources",
      content: <>
        <FieldList rows={[
          ["Report ID", getString(report?.report_id)],
          ["Assessment ID", getString(assessment?.assessment_id)],
          ["Oracle narrative ID", getString(oracleNarrative?.narrative_id)],
          ["ModelDock call", getString(modeldockProvenance?.call_id)],
          ["ModelDock status", getString(modeldockProvenance?.status)],
          ["Latency ms", getNumber(modeldockProvenance?.latency_ms)?.toString()],
          ["Mocked", getBoolean(modeldockProvenance?.mocked) === undefined ? undefined : getBoolean(modeldockProvenance?.mocked) ? "Yes" : "No"],
          ["Observed at", getString(modeldockProvenance?.observed_at)],
        ]} />
      </>,
      evidencePaths: evidencePaths(viewModel, ["oracle_report", "oracle_assessment", "oracle_narrative", "oracle_modeldock_provenance"]),
    },
  ];
}

function councilPages(viewModel: MissionViewModel): BookPage[] {
  const synthesis = getEvidenceDocument(viewModel, "council_synthesis");
  const executive = getEvidenceDocument(viewModel, "council_executive_summary");
  const candidates = getEvidenceDocument(viewModel, "council_candidate_evidence");
  const senateReview = getEvidenceDocument(viewModel, "council_senate_review_evidence");
  const deliberation = getEvidenceDocument(viewModel, "council_senate_deliberation_evidence");
  const mandate = getEvidenceDocument(viewModel, "council_mandate_policy");
  return [
    {
      id: "council-synthesis",
      title: "Synthesis",
      eyebrow: "Council native result",
      content: <>
        <EvidenceState viewModel={viewModel} name="council_synthesis" />
        <p className="book-lede">{field(synthesis, "council_summary")}</p>
        <FieldList rows={[
          ["Synthesis state", getString(synthesis?.synthesis_state)],
          ["Advisors", getNumber(synthesis?.advisor_count)?.toString()],
          ["Opportunity", getString(synthesis?.opportunity_posture)],
          ["Permission", getString(synthesis?.permission_posture)],
          ["Market structure", getString(synthesis?.market_structure_posture)],
          ["Future state", getString(synthesis?.future_state_posture)],
          ["Accountability", getString(synthesis?.accountability_posture)],
        ]} />
      </>,
      evidencePaths: evidencePaths(viewModel, ["council_synthesis"]),
    },
    {
      id: "council-agreement",
      title: "Agreement and dissent",
      eyebrow: "Meaningful disagreement preserved",
      content: <>
        <h3>Alignments</h3>
        <BulletList values={list(synthesis, "key_alignments")} />
        <h3>Conflicts</h3>
        <BulletList values={list(synthesis, "key_conflicts")} />
        <h3>Executive conflicts</h3>
        <BulletList values={list(executive, "notable_conflicts")} />
        <p className="book-note">No Council agreement percentage is present in the canonical evidence.</p>
      </>,
      evidencePaths: evidencePaths(viewModel, ["council_synthesis", "council_executive_summary"]),
    },
    {
      id: "council-evidence",
      title: "Supporting evidence",
      eyebrow: "Candidate, Senate, and Mandate context",
      content: <>
        <FieldList rows={[
          ["Candidates", getNumber(candidates?.candidate_count)?.toString()],
          ["Candidate WATCH", getNumber(candidates?.watch_count)?.toString()],
          ["Senate DISCUSS", getNumber(senateReview?.discuss_count)?.toString()],
          ["Senate MONITOR", getNumber(deliberation?.monitor_count)?.toString()],
          ["Senate summary", getString(deliberation?.summary)],
          ["Mandate status", getBoolean(mandate?.ok) === undefined ? undefined : getBoolean(mandate?.ok) ? "OK" : "NOT OK"],
          ["Mandate risk posture", getString(mandate?.risk_posture)],
        ]} />
        <p className="book-note">Candidate evidence is not a live watchlist or trade recommendation.</p>
      </>,
      evidencePaths: evidencePaths(viewModel, ["council_candidate_evidence", "council_senate_review_evidence", "council_senate_deliberation_evidence", "council_mandate_policy"]),
    },
    {
      id: "council-executive",
      title: "Executive summary",
      eyebrow: "Canonical Council brief",
      content: <>
        <p className="book-lede">{field(executive, "headline")}</p>
        <p>{field(executive, "executive_summary")}</p>
        <h3>Key points</h3>
        <BulletList values={list(executive, "key_points")} />
        <h3>Operator attention</h3>
        <BulletList values={list(executive, "operator_attention_items")} />
      </>,
      evidencePaths: evidencePaths(viewModel, ["council_executive_summary"]),
    },
  ];
}

function governorPages(viewModel: MissionViewModel): BookPage[] {
  const rendered = getEvidenceDocument(viewModel, "governor_rendered_decision");
  const readiness = getEvidenceDocument(viewModel, "governor_decision_readiness");
  const decision = getEvidenceDocument(viewModel, "governor_decision");
  const deliberation = getEvidenceDocument(viewModel, "governor_deliberation");
  const classifications = getEvidenceDocument(viewModel, "governor_warning_classification");
  return [
    {
      id: "governor-disposition",
      title: "Rendered disposition",
      eyebrow: "Governor result",
      content: <>
        <EvidenceState viewModel={viewModel} name="governor_rendered_decision" />
        <FieldList rows={[
          ["Disposition", getString(rendered?.disposition)],
          ["Decision status", getString(rendered?.decision_status)],
          ["Posture", getString(rendered?.posture)],
          ["Decision ID", getString(rendered?.decision_id)],
          ["Rendered at", getString(rendered?.rendered_at)],
        ]} />
        <p className="book-note">Governor PROCEED is not mission approval and does not authorize a trade.</p>
      </>,
      evidencePaths: evidencePaths(viewModel, ["governor_rendered_decision"]),
    },
    {
      id: "governor-readiness",
      title: "Readiness and warnings",
      eyebrow: "Decision gate",
      content: <>
        <FieldList rows={[
          ["Readiness", getString(readiness?.readiness_state)],
          ["Ready for decision", getBoolean(readiness?.ready_for_decision) === undefined ? undefined : getBoolean(readiness?.ready_for_decision) ? "Yes" : "No"],
          ["Required conditions", getBoolean(readiness?.required_conditions_met) === undefined ? undefined : getBoolean(readiness?.required_conditions_met) ? "Met" : "Not met"],
          ["Summary", getString(readiness?.summary)],
        ]} />
        <h3>Routine warnings</h3>
        <BulletList values={list(classifications, "routine_warnings")} />
        <h3>Decision warnings</h3>
        <BulletList values={list(classifications, "decision_warnings")} />
      </>,
      evidencePaths: evidencePaths(viewModel, ["governor_decision_readiness", "governor_warning_classification"]),
    },
    {
      id: "governor-rationale",
      title: "Decision rationale",
      eyebrow: "Recorded reasoning",
      content: <>
        <p className="book-lede">{field(decision, "governor_rationale")}</p>
        <h3>Preparation reasoning</h3>
        <BulletList values={list(deliberation, "governor_reasoning")} />
        <FieldList rows={[
          ["Market interpretation", getString(deliberation?.market_interpretation)],
          ["Council interpretation", getString(deliberation?.council_interpretation)],
          ["Mandate interpretation", getString(deliberation?.mandate_interpretation)],
          ["Accountability", getString(deliberation?.accountability_interpretation)],
        ]} />
      </>,
      evidencePaths: evidencePaths(viewModel, ["governor_decision", "governor_deliberation"]),
    },
    {
      id: "governor-next-step",
      title: "Allowed next step",
      eyebrow: "Operator boundary",
      content: <>
        <FieldList rows={[
          ["Allowed next step", getString(rendered?.allowed_next_step)],
          ["Operator route", viewModel.status.operatorRoute ?? undefined],
          ["Operator result", viewModel.status.operatorResult ?? undefined],
          ["Mission outcome", viewModel.status.outcome],
          ["Approval scope", viewModel.status.approvalScope ?? undefined],
        ]} />
        <p className="book-note">Only the explicitly recorded operator result may advance the mission to Navigator.</p>
      </>,
      evidencePaths: evidencePaths(viewModel, ["governor_rendered_decision", "operator_action"]),
    },
  ];
}

function navigatorPages(viewModel: MissionViewModel): BookPage[] {
  const review = getEvidenceDocument(viewModel, "operator_review_packet");
  const action = getEvidenceDocument(viewModel, "operator_action");
  const handoff = getEvidenceDocument(viewModel, "navigator_handoff_envelope");
  const staging = getEvidenceDocument(viewModel, "navigator_staging_receipt");
  const intake = getEvidenceDocument(viewModel, "navigator_intake_receipt");
  const plan = getEvidenceDocument(viewModel, "navigator_shadow_plan");
  const constraints = getObject(plan?.validated_constraints);
  return [
    {
      id: "navigator-handoff",
      title: "Operator handoff",
      eyebrow: "Explicit approval event",
      content: <>
        <FieldList rows={[
          ["Governor state", getString(review?.decision_state)],
          ["Operator route", getString(review?.operator_route)],
          ["Action", getString(action?.action)],
          ["Result", getString(action?.resulting_status)],
          ["Operator", getString(action?.operator_id)],
          ["Action ID", getString(action?.action_id)],
          ["Reason", getString(action?.reason)],
        ]} />
      </>,
      evidencePaths: evidencePaths(viewModel, ["operator_review_packet", "operator_action", "operator_receipt"]),
    },
    {
      id: "navigator-intake",
      title: "Intake status",
      eyebrow: "Validated SHADOW envelope",
      content: <FieldList rows={[
        ["Handoff", getString(staging?.status)],
        ["Handoff ID", getString(staging?.handoff_id)],
        ["Mode", getString(staging?.mode)],
        ["Staged at", getString(staging?.staged_at)],
        ["Intake", getString(intake?.status)],
        ["Accepted at", getString(intake?.accepted_at)],
      ]} />,
      evidencePaths: evidencePaths(viewModel, ["navigator_handoff_envelope", "navigator_staging_receipt", "navigator_intake_receipt"]),
    },
    {
      id: "navigator-plan",
      title: "SHADOW plan",
      eyebrow: "Plan only — no execution",
      content: <>
        <FieldList rows={[
          ["Plan status", getString(plan?.planning_status)],
          ["Plan ID", getString(plan?.plan_id)],
          ["Created at", getString(plan?.created_at)],
          ["Expires at", getString(plan?.expires_at)],
        ]} />
        <h3>Observations</h3>
        <BulletList values={list(plan, "observations")} />
        <h3>Next analytical steps</h3>
        <BulletList values={list(plan, "proposed_next_analytical_steps")} />
      </>,
      evidencePaths: evidencePaths(viewModel, ["navigator_shadow_plan"]),
    },
    {
      id: "navigator-allowed",
      title: "Allowed operations",
      eyebrow: "Exact canonical envelope",
      content: <>
        <p className="book-safety">{viewModel.safety.displayStatement}</p>
        <BulletList values={viewModel.safety.allowedOperations} />
      </>,
      evidencePaths: evidencePaths(viewModel, ["navigator_handoff_envelope", "navigator_shadow_plan"]),
    },
    {
      id: "navigator-prohibited",
      title: "Prohibited operations",
      eyebrow: "Execution boundary",
      content: <>
        <p className="book-safety">No trade or order execution.</p>
        <BulletList values={viewModel.safety.prohibitedOperations} />
      </>,
      evidencePaths: evidencePaths(viewModel, ["navigator_handoff_envelope", "navigator_shadow_plan"]),
    },
    {
      id: "navigator-final",
      title: "Final mission result",
      eyebrow: "Canonical mission state",
      content: <>
        <FieldList rows={[
          ["Handoff", getString(handoff?.handoff_status)],
          ["Intake", getString(intake?.status)],
          ["Plan", getString(plan?.planning_status)],
          ["Mode", getString(constraints?.mode) ?? viewModel.status.navigatorMode ?? undefined],
          ["Mission outcome", viewModel.status.outcome],
          ["Approval scope", viewModel.status.approvalScope ?? undefined],
        ]} />
        <p className="book-safety">{viewModel.safety.displayStatement}</p>
      </>,
      evidencePaths: evidencePaths(viewModel, ["navigator_handoff_envelope", "navigator_intake_receipt", "navigator_shadow_plan"]),
    },
  ];
}

export function buildBookDefinitions(viewModel: MissionViewModel): readonly BookDefinition[] {
  return [
    {
      id: "harbormaster",
      title: "Harbormaster",
      subtitle: "Mission control & integrity",
      state: viewModel.stages.harbormaster.displayState,
      deskLines: [viewModel.stages.harbormaster.summary, `Snapshots: ${viewModel.status.snapshotCount}`],
      pages: requestPages(viewModel),
      accent: "#355f78",
    },
    {
      id: "oracle",
      title: "Oracle",
      subtitle: "Facts, diagnostics & readiness",
      state: viewModel.stages.oracle.displayState,
      deskLines: [viewModel.stages.oracle.summary, `Native state: ${viewModel.stages.oracle.nativeState ?? "Not recorded"}`],
      pages: oraclePages(viewModel),
      accent: "#6b478f",
    },
    {
      id: "council",
      title: "Council",
      subtitle: "Synthesis without score invention",
      state: viewModel.stages.council.displayState,
      deskLines: [viewModel.stages.council.summary, `Native state: ${viewModel.stages.council.nativeState ?? "Not recorded"}`],
      pages: councilPages(viewModel),
      accent: "#9b6818",
    },
    {
      id: "governor",
      title: "Governor",
      subtitle: "Rendered disposition",
      state: viewModel.stages.governor.displayState,
      deskLines: [
        `Disposition: ${viewModel.status.governorDisposition ?? "Not recorded"}`,
        `Operator: ${viewModel.status.operatorResult ?? "Not recorded"}`,
        "PROCEED is not mission approval.",
      ],
      pages: governorPages(viewModel),
      accent: "#8d382e",
    },
    {
      id: "navigator",
      title: "Navigator",
      subtitle: "SHADOW handoff & plan",
      state: viewModel.stages.navigator.displayState,
      deskLines: [
        `Handoff: ${viewModel.status.navigatorHandoffStatus ?? "Not recorded"}`,
        `Intake: ${viewModel.status.navigatorIntakeStatus ?? "Not recorded"}`,
        `${viewModel.status.navigatorMode ?? "Not recorded"} · ${viewModel.status.navigatorPlanStatus ?? "Not recorded"}`,
      ],
      pages: navigatorPages(viewModel),
      accent: "#2f6d4d",
    },
  ];
}
