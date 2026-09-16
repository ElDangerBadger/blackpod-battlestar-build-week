import type { ReactNode } from "react";
import type { JsonObject } from "../contracts/presentation";
import { getEvidence, getEvidenceDocument, type MissionViewModel, type StageBookId } from "../data/viewModel";
import { getNumber, getString, getStringArray } from "../data/validate";
import { explainMissionWarning } from "../components/MissionWarnings";
import { ModelDockNarrativeDetails, OracleMarketNarrative } from "./OracleNarrative";

type Briefing = { headline: string; explanation: string; points?: readonly [string, string][]; limit?: string };

// Presentation glosses only. Meanings are bounded by canonical Council synthesis
// and Oracle narrative logic; unfamiliar values remain explicitly uninterpreted.
const MEANINGS: Readonly<Record<string, string>> = {
  NO_OPPORTUNITY_SIGNAL: "No Senate decisions were supplied to this synthesis. This does not mean that no market opportunities exist.",
  HOLD_OR_NEUTRAL: "The supplied Senate decisions are hold, neutral, or no-action positions.",
  RESTRICTED_PERMISSION: "The recorded mandate does not permit action.",
  STALE_PERMISSION: "The permission input is marked stale; it is not current authority.",
  PERMITTED: "The supplied mandate is permissive. This alone is not operator approval or trading authority in the Cabin.",
  MIXED_MARKET_STRUCTURE: "The supplied Oracle context was not classified as clearly risk-on or risk-off. This is not an agreement score.",
  RISK_ON_MARKET_STRUCTURE: "The supplied Oracle context is classified as risk-on; this is market context, not an instruction to act.",
  RISK_OFF_MARKET_STRUCTURE: "The supplied Oracle context is classified as risk-off or defensive; this is market context, not an instruction to act.",
  FUTURE_STATE_MISSING: "No usable forward-scenario input was supplied to Council. A future outcome has not been established.",
  ACCOUNTABILITY_MISSING: "No Secretary accountability dossier or scorecards were supplied to Council. This is missing context, not a finding of wrongdoing.",
  MEMORY_MISSING: "No historical market-context input was supplied to Council.",
  CONTRACTING_BREADTH: "Market participation is contracting across the measured universe.",
  STABLE_BREADTH: "Market participation is stable across the measured universe.",
  EXPANDING_BREADTH: "Market participation is broadening across the measured universe.",
  MIXED_LEADERSHIP: "Leadership is neither broadly distributed nor tightly concentrated.",
  BROAD_LEADERSHIP: "Leadership is spread across a larger portion of the measured market.",
  NARROW_LEADERSHIP: "Leadership is concentrated in a limited number of sectors.",
  MIXED_ROTATION: "Sector rotation is mixed between defensive and cyclical groups.",
  CYCLICAL_ROTATION: "Cyclical sectors show greater relative strength in this assessment.",
  DEFENSIVE_ROTATION: "Defensive sectors show greater relative strength in this assessment.",
  NEUTRAL: "The recorded market structure reflects a balanced risk posture.",
  RISK_ON: "The recorded market structure reflects a constructive risk posture.",
  RISK_OFF: "The recorded market structure reflects a defensive risk posture.",
};

export function explainRecordedCode(value: string | undefined): string {
  if (!value) return "Not recorded in the supplied evidence; no conclusion is available.";
  return Object.hasOwn(MEANINGS, value) ? MEANINGS[value] : `Recorded as “${value}”. No plain-language interpretation is defined for this value.`;
}

export function processLabel(value: string): string {
  const labels: Record<string, string> = {
    SUCCEEDED: "Process completed", FAILED: "Process failed", NOT_STARTED: "Not started",
    RUNNING: "In progress", SKIPPED: "Skipped",
  };
  return Object.hasOwn(labels, value) ? labels[value] : value;
}

const strings = (doc: JsonObject | undefined, key: string) => getStringArray(doc?.[key]);
const count = (doc: JsonObject | undefined, key: string) => getNumber(doc?.[key])?.toString() ?? "Not recorded";
const code = (doc: JsonObject | undefined, key: string) => explainRecordedCode(getString(doc?.[key]));
const noTrade = (doc: JsonObject | undefined, key: string) => strings(doc, key)?.some((value) => value === "mandate:READ_ONLY_DATA_RUN_NO_TRADING_AUTHORITY") === true;
const summary = (doc: JsonObject | undefined, key: string) => getString(doc?.[key]) ?? "No narrative was recorded in the supplied evidence.";
const listed = (doc: JsonObject | undefined, key: string) => {
  const values = strings(doc, key);
  return values === undefined ? "Not recorded in the supplied evidence." : values.length === 0 ? "No items listed in this artifact." : values.join(" ");
};
const warnings = (doc: JsonObject | undefined, key: string) => {
  const values = strings(doc, key);
  if (!values || values.length === 0) return listed(doc, key);
  return values.map((value) => {
    const explained = explainMissionWarning(value);
    return `${explained.meaning} ${explained.impact}`;
  }).join(" ");
};

function briefingFor(viewModel: MissionViewModel, pageId: string): Briefing {
  const request = getEvidenceDocument(viewModel, "mission_request");
  const oracle = getEvidenceDocument(viewModel, "oracle_report");
  const diagnostics = getEvidenceDocument(viewModel, "oracle_measurement_diagnostics");
  const modelEvidence = getEvidence(viewModel, "oracle_modeldock_narrative");
  const narrative = modelEvidence?.status === "LOADED" ? modelEvidence.document ?? undefined : undefined;
  const council = getEvidenceDocument(viewModel, "council_synthesis");
  const executive = getEvidenceDocument(viewModel, "council_executive_summary");
  const mandate = getEvidenceDocument(viewModel, "council_mandate_policy");
  const rendered = getEvidenceDocument(viewModel, "governor_rendered_decision");
  const decision = getEvidenceDocument(viewModel, "governor_decision");
  const readiness = getEvidenceDocument(viewModel, "governor_decision_readiness");
  const plan = getEvidenceDocument(viewModel, "navigator_shadow_plan");
  const councilState = getString(council?.synthesis_state);
  const disposition = getString(rendered?.disposition);
  const actualNoTrade = noTrade(council, "blockers") || noTrade(rendered, "blocking_reasons");
  const noTradeMeaning = actualNoTrade
    ? "This run has an explicit read-only mandate: it permits analysis but grants no trading authority. That restriction is a recorded blocker, not a software failure."
    : "Only the recorded decision and any separately recorded operator approval establish the next permitted step. Completing a review does not grant authority.";
  const noAction = viewModel.status.operatorResult === null;
  const authorityLimit = "This Cabin is read-only. It cannot approve a handoff, place an order, or execute a trade.";

  switch (pageId) {
    case "harbormaster-request": return {
      headline: viewModel.stages.harbormaster.technicalStatus === "SUCCEEDED" ? "Mission received and recorded" : processLabel(viewModel.stages.harbormaster.technicalStatus),
      explanation: request ? `This ledger identifies the request for ${getString(request.symbol) ?? "an unrecorded symbol"} and the evidence collected for it.` : "The mission request artifact is not available. The Cabin does not reconstruct missing submission details.",
      points: [["What happened", "Harbormaster tracks mission intake and record integrity; it does not make a market decision."], ["Current mission", `Recorded outcome: ${viewModel.status.outcome}. Recorded phase: ${viewModel.status.currentPhase}.`]],
      limit: "A named request operator identifies who submitted the mission, not who approved a handoff.",
    };
    case "harbormaster-identity": return { headline: "Which mission am I reading?", explanation: `These identifiers tie the ${viewModel.status.symbol} request to its saved mission record. They are useful when comparing evidence or reporting an issue.`, points: [["Mission", viewModel.status.missionId], ["Request", viewModel.status.requestId]], limit: "Identifiers describe this record only; they do not indicate that market data is streaming." };
    case "harbormaster-integrity": return { headline: "A traceable record of the run", explanation: `${viewModel.status.snapshotCount} mission snapshots are recorded. Each snapshot preserves a point in the mission’s progression.`, points: [["Run state", viewModel.status.terminal ? "This recorded mission has reached a terminal state." : "This recorded mission has not reached a terminal state."], ["Integrity", "The recorded SHA-256 fingerprint identifies the final snapshot. It is an integrity reference, not a confidence score."]], limit: "A terminal state can be approved, held, vetoed, or failed; it does not necessarily mean permission to act." };
    case "harbormaster-revisions": return { headline: "Where the evidence came from", explanation: "The recorded software revisions and service identities identify which components produced this mission’s artifacts.", limit: "These are the versions recorded for this run, not a claim about the software currently deployed." };
    case "oracle-assessment": return {
      headline: getString(oracle?.headline) ?? "Market assessment not recorded",
      explanation: "Oracle describes the measured market universe. Its broad-market assessment is separate from the selected symbol’s Navigator price chart.",
      limit: "Process completion means Oracle ran. A recorded READY diagnostic result describes its input checks; neither establishes complete data or recommends a trade. Missing or excluded inputs remain limitations.",
    };
    case "oracle-measurements": return { headline: "The measurements behind the assessment", explanation: "These recorded measures describe participation, relative strength, leadership concentration, rotation, and dispersion across the validation fleet.", points: [["How to read the numbers", "Each measure retains its source value and scale. The Cabin does not convert these values into approval probabilities or a new combined score."], ["Change over time", viewModel.warnings.includes("MISSING_PRIOR_ORACLE_MEASUREMENTS") ? "Prior measurements were unavailable or not sufficiently comparable. A recorded zero rotation velocity must not be read as evidence that no rotation occurred." : "Change measures depend on the prior observations supplied to Oracle."]], limit: "Fleet measurements do not establish an individual security’s suitability or a trading decision." };
    case "oracle-diagnostics": return { headline: "How much evidence was usable?", explanation: "Diagnostics describe the inputs Oracle actually used and the checks applied to them.", points: [["Symbols used", count(diagnostics, "symbols_used_count")], ["Excluded / missing", `${count(diagnostics, "symbols_excluded_count")} excluded; ${count(diagnostics, "symbols_missing_count")} missing.`], ["Fallback inputs", count(diagnostics, "fallback_count")]], limit: "Excluded symbols are outside the accepted Oracle snapshot set; they are not automatically failed data requests. Readiness is an input-quality check, not action approval." };
    case "oracle-modeldock": return { headline: "Model commentary, kept separate from facts", explanation: summary(narrative, "summary"), points: [["Interpretation", summary(narrative, "interpretation")]], limit: "This is recorded model commentary, not a new analysis request. Oracle remains authoritative for measurements, diagnostics, and readiness; the commentary cannot grant trading authority." };
    case "oracle-warnings": return { headline: "Limits to keep in mind", explanation: "Warnings qualify how the assessment should be read. They do not all represent failed software or blocked decisions.", points: [["Oracle warnings", warnings(oracle, "warnings")], ["Model uncertainty", listed(narrative, "uncertainties")]], limit: "No listed warnings is not proof of complete data or certainty. Original wording is preserved below." };
    case "oracle-provenance": return { headline: "Trace this assessment to its sources", explanation: "Report IDs connect the assessment, narrative, and any model call. The evidence links below open the original saved artifacts.", limit: "Model latency and trace IDs describe the recorded call, not current availability or live market freshness." };
    case "council-synthesis": return {
      headline: councilState === "BLOCKED" ? "Review result: not cleared for action" : councilState === "MIXED" ? "Council recorded a mixed result" : councilState ? `Council result: ${councilState}` : "Council result not recorded",
      explanation: `${viewModel.stages.council.technicalStatus === "SUCCEEDED" ? "The Council process completed successfully. That means a review was produced, not that action was approved. " : "The technical process state and the review’s conclusion are separate. "}${noTradeMeaning}`,
      points: [["Inputs reviewed", `${count(council, "advisor_count")} advisory input sources are recorded. These are sources, not a count of AI models.`], ["Opportunity context", code(council, "opportunity_posture")], ["Permission", code(council, "permission_posture")], ["Market context", code(council, "market_structure_posture")], ["Forward scenarios", code(council, "future_state_posture")], ["Accountability context", code(council, "accountability_posture")]],
      limit: "A blocked Council result can still be passed to Governor for review. Missing context is not a negative forecast, and no Council agreement percentage is inferred.",
    };
    case "council-agreement": return { headline: "Where the inputs align—or differ", explanation: "Council preserves explicitly recorded alignments and conflicts instead of inventing a consensus score.", points: [["Recorded alignments", listed(council, "key_alignments")], ["Recorded conflicts", listed(council, "key_conflicts")]], limit: "Empty lists mean no items were listed in this artifact; they do not prove unanimous agreement." };
    case "council-evidence": return { headline: "What Council had to work with", explanation: "Candidate and Senate records supply review context. The mandate supplies the permission boundary; it is not a market forecast.", points: [["Mandate", getString(mandate?.reason) === "READ_ONLY_DATA_RUN_NO_TRADING_AUTHORITY" ? "Analysis only: no allowed trading sides and no trading authority for this run." : "The exact supplied mandate status and risk posture are preserved below."]], limit: "WATCH, DISCUSS, and MONITOR are recorded workflow classifications, not instructions to buy or sell." };
    case "council-executive": return { headline: "Council’s overall takeaway", explanation: councilState === "BLOCKED" ? noTradeMeaning : summary(executive, "executive_summary"), points: [["Items requiring attention", listed(executive, "operator_attention_items")]], limit: "The recorded executive summary may also identify missing history or scenario context. Those gaps are not filled with invented conclusions." };
    case "governor-disposition": return { headline: disposition === "BLOCKED" ? "Decision recorded: action is blocked" : disposition === "PROCEED" ? "Proceed to the recorded review step—not to a trade" : disposition ? `Governor decision: ${disposition}` : "Governor decision not recorded", explanation: `${viewModel.stages.governor.technicalStatus === "SUCCEEDED" ? "The Governor process completed and produced a decision. " : "A completed process and a permissive decision are different things. "}${noTradeMeaning}`, points: [["Next recorded step", getString(rendered?.allowed_next_step) === "NONE" ? "None. The decision does not authorize an onward action." : getString(rendered?.allowed_next_step) ?? "No next step is recorded."]], limit: "A PROCEED disposition is only one gate; it never authorizes a trade on its own." };
    case "governor-readiness": return { headline: "The checks behind the decision", explanation: getString(readiness?.readiness_state) === "BLOCKED" ? "One or more required inputs are blocking the decision gate. A decision can still be rendered to record that blocked result." : "Readiness describes whether the supplied context meets the decision gate’s conditions.", points: [["Recorded blockers", count(readiness, "blocker_count")], ["Permission boundary", noTradeMeaning]], limit: "Routine data warnings are separate from decision-blocking warnings. Original classifications are preserved below." };
    case "governor-rationale": return { headline: "Why this decision was recorded", explanation: actualNoTrade ? noTradeMeaning : summary(decision, "governor_rationale"), points: [["Reading the sequence", "Preparation notes describe the briefing before the final decision. An earlier “not rendered” note does not override the later rendered decision."], ["Different evidence roles", "Market, Council, mandate, and accountability inputs are separate parts of the briefing. Presence of a briefing section does not prove every underlying source is complete."]], limit: "The recorded final decision is the result; this page does not create a new judgment." };
    case "governor-next-step": return { headline: "What is authorized next?", explanation: getString(rendered?.allowed_next_step) === "NONE" ? "The Governor decision allows no next step. The mission remains at its recorded outcome." : "A permissive Governor result is not enough on its own: any handoff also requires the explicitly recorded operator result.", points: [["Operator approval", noAction ? "No operator result is recorded." : `Recorded operator result: ${viewModel.status.operatorResult}.`], ["Mission outcome", viewModel.status.outcome]], limit: authorityLimit };
    case "navigator-handoff": return { headline: noAction ? "No operator handoff is recorded" : "Read the recorded operator handoff", explanation: noAction ? "This mission has no recorded operator result authorizing an operational Navigator handoff. The separate market-reference chart can still be available for viewing." : "This page records the operator’s explicit action. Handoff approval is limited to the stated scope; it is not permission to execute a trade.", points: [["Operational Navigator", viewModel.status.navigatorPlanStatus ? `Recorded plan status: ${viewModel.status.navigatorPlanStatus}.` : "No operational plan status is recorded."], ["Market reference", "The Navigator Reference Tape and Ship View show supplemental captured market data, not the output of an operational SHADOW plan."]], limit: authorityLimit };
    case "navigator-intake": return { headline: "Was a handoff received?", explanation: viewModel.status.navigatorIntakeStatus === null ? "No intake status is recorded for this mission. Missing intake is not presented as an accepted handoff." : `The recorded intake status is ${viewModel.status.navigatorIntakeStatus}. Staging and intake are separate checks on the supplied SHADOW envelope.`, limit: "Acceptance validates an envelope; it does not send an order." };
    case "navigator-plan": return { headline: plan ? "A plan for analysis, not execution" : "No SHADOW plan artifact is available", explanation: plan ? "Any observations and proposed analytical steps below are the recorded plan. They do not represent executed activity." : "There is no plan content to display in the supplied evidence. The market-reference chart does not fill this gap or imply a plan was created.", limit: authorityLimit };
    case "navigator-allowed": return { headline: "Validation and planning only", explanation: "The Cabin’s safety envelope allows validation and plan-only work. These are restrictions, not evidence that an operator approved a handoff.", limit: "SHADOW mode permits no trade or order execution." };
    case "navigator-prohibited": return { headline: "No trading actions are available", explanation: "Order submission, cancellation, modification, portfolio changes, and broker calls are prohibited. The exact operation names are preserved below.", limit: authorityLimit };
    case "navigator-final": return { headline: `Recorded mission outcome: ${viewModel.status.outcome}`, explanation: viewModel.status.navigatorPlanStatus === null ? "No Navigator plan status is recorded. This page does not turn a completed review or a visible market chart into an approved plan." : `The operational plan status is ${viewModel.status.navigatorPlanStatus}; it remains within the recorded SHADOW-only scope.`, limit: authorityLimit };
    default: return { headline: "Read the saved mission evidence", explanation: "Exact recorded values and source links are preserved below." };
  }
}

export function withLedgerBriefing(viewModel: MissionViewModel, bookId: StageBookId, pageId: string, recordedContent: ReactNode): ReactNode {
  const briefing = briefingFor(viewModel, pageId);
  const stage = viewModel.stages[bookId];
  return <>
    <section className="ledger-briefing" aria-label="Plain-language reading">
      <p className="ledger-takeaway">{briefing.headline}</p>
      <p>{briefing.explanation}</p>
      {pageId === "oracle-assessment" ? <OracleMarketNarrative viewModel={viewModel} /> : null}
      {briefing.points ? <dl className="ledger-meaning-list">{briefing.points.map(([label, text]) => <div key={label}><dt>{label}</dt><dd>{text}</dd></div>)}</dl> : null}
      {pageId === "oracle-modeldock" ? <ModelDockNarrativeDetails viewModel={viewModel} /> : null}
      {briefing.limit ? <p className="ledger-boundary"><strong>Keep in mind:</strong> {briefing.limit}</p> : null}
    </section>
    <details className="ledger-recorded-details">
      <summary>Recorded details · exact values</summary>
      <div>
        <p className="ledger-recorded-status">Process status: <code>{stage.technicalStatus}</code> · Native result: <code>{stage.nativeState ?? "Not recorded"}</code> · Display state: <code>{stage.displayState}</code></p>
        {recordedContent}
      </div>
    </details>
  </>;
}
