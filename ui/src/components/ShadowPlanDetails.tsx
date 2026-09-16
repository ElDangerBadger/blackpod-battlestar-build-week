import { getEvidenceDocument, type MissionViewModel } from "../data/viewModel";
import { missionRelativeUrl } from "../data/loadMission";
import { getString, getStringArray } from "../data/validate";
import "./shadow-plan-details.css";

export function ShadowPlanDetails({ mission, onOpenBook }: { mission: MissionViewModel; onOpenBook: () => void }) {
  const plan = getEvidenceDocument(mission, "navigator_shadow_plan");
  const reference = mission.evidence.get("navigator_shadow_plan")?.reference;
  const analysisOnly = mission.warnings.some((warning) => warning === "READ_ONLY_DATA_RUN_NO_TRADING_AUTHORITY"
    || warning === "Mandate is valid but does not permit action: READ_ONLY_DATA_RUN_NO_TRADING_AUTHORITY");
  const facts = [
    ["Navigator process", mission.stages.navigator.technicalStatus],
    ["Governor decision", mission.status.governorDisposition],
    ["Operator result", mission.status.operatorResult],
    ["Approval scope", mission.status.approvalScope],
    ["Handoff", mission.status.navigatorHandoffStatus],
    ["Intake", mission.status.navigatorIntakeStatus],
    ["Recorded plan status", mission.status.navigatorPlanStatus],
    ["Recorded mode", mission.status.navigatorMode],
  ];
  return <div className="shadow-plan-details">
    <p className="notice-lede">{plan ? "A captured SHADOW plan is available to read." : "No SHADOW plan artifact is available for this mission."}</p>
    <p>A SHADOW plan is an analytical record, not an order. This panel opens the saved evidence; it does not activate Navigator or start a mission.</p>
    {analysisOnly ? <p className="panel-boundary">This run was explicitly authorized for analysis only, without trading authority. Its blocked action decision is not a failed data run.</p> : null}
    <dl className="reference-tape-facts">{facts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value ?? "Not recorded"}</dd></div>)}</dl>
    {plan ? <section aria-label="Recorded SHADOW plan content">
      <h3>Plan contents</h3>
      <p>Plan ID: {getString(plan.plan_id) ?? "Not recorded"}</p>
      <h3>Recorded observations</h3>
      <PlanItems values={getStringArray(plan.observations)} />
      <h3>Recorded next analytical steps</h3>
      <PlanItems values={getStringArray(plan.proposed_next_analytical_steps)} />
      <details className="recorded-details"><summary>Original plan · exact recorded values</summary><pre>{JSON.stringify(plan, null, 2)}</pre></details>
      {reference ? <p><a href={missionRelativeUrl(mission.baseUrl, reference.path)} target="_blank" rel="noreferrer">Open original SHADOW plan artifact</a></p> : null}
    </section> : <p>The price chart and Reference Tape are supplemental market context. Their availability does not mean an operational plan was created.</p>}
    <section aria-label="How a SHADOW plan becomes available">
      <h3>How a plan becomes available</h3>
      <ol>
        <li>The canonical mission must reach a disposition that permits the operator review step. Governor <code>PROCEED</code> alone is not approval.</li>
        <li>An authorized operator must explicitly record approval for the <code>NAVIGATOR_SHADOW_HANDOFF</code> scope.</li>
        <li>Navigator must receive and validate the handoff, then produce a plan within its SHADOW-only boundary.</li>
      </ol>
      <p>Those actions belong to the mission workflow, not this read-only Cabin. There is no activation or approval control here, and no trade or order execution is enabled.</p>
    </section>
    <button type="button" onClick={onOpenBook}>Read full Navigator ledger</button>
  </div>;
}

function PlanItems({ values }: { values: string[] | undefined }) {
  if (!values) return <p>Not supplied in this artifact.</p>;
  if (!values.length) return <p>No items listed in this artifact.</p>;
  return <ul>{values.map((value, index) => <li key={index}>{value}</li>)}</ul>;
}
