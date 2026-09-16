import type { ReactNode } from "react";
import type { ArtifactReference } from "../contracts/presentation";
import type { MissionEvidenceName } from "../data/loadMission";
import { missionRelativeUrl } from "../data/loadMission";
import { getEvidence, getEvidenceDocument, type MissionViewModel, type StageBookId } from "../data/viewModel";
import { getString, getStringArray } from "../data/validate";
import { explainRecordedCode, processLabel } from "../books/ledgerBriefings";
import type { CabinPanelId } from "./cabinPanelTypes";
import { FleetOverview } from "./FleetOverview";
import { LocalWatchlist } from "./LocalWatchlist";
import { MissionWarnings } from "./MissionWarnings";
import { NavigatorMarketProvenance } from "./NavigatorMarketProvenance";
import "./cabin-panel-details.css";

export const CABIN_PANEL_TITLES: Record<CabinPanelId, string> = {
  market: "Market context", fleet: "Fleet status", modeldock: "ModelDock provenance",
  timeframe: "Timeframe & recorded observations", mission: "Current mission",
  "market-timing": "Market capture timing", "mission-time": "Mission timestamps",
  approval: "Approval scope", watchlist: "Local watchlist & fleet coverage",
  governance: "Risk & governance", governor: "Governor decision",
  portfolio: "Portfolio exposure", "model-routing": "ModelDock routing", safety: "Safety boundary",
};

type Props = {
  panel: CabinPanelId;
  mission: MissionViewModel;
  onOpenBook?: (id: StageBookId) => void;
  onOpenWatchlist?: () => void;
  onOpenNavigator?: (symbol: string) => void;
  onOpenReferenceTape?: (symbol: string) => void;
};
type Row = readonly [string, ReactNode];
const MISSING = "Not recorded";

function Facts({ rows }: { rows: readonly Row[] }) {
  return <dl className="cabin-detail-facts">{rows.map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value ?? MISSING}</dd></div>)}</dl>;
}

function Timestamp({ value }: { value: string | null | undefined }) {
  if (!value) return <>{MISSING}</>;
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return <code>{value}</code>;
  return <time dateTime={value} title={value}>{new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium", timeStyle: "medium", timeZone: "UTC",
  }).format(date)} UTC</time>;
}

function EvidenceLinks({ mission, names, extra = [] }: {
  mission: MissionViewModel;
  names: readonly string[];
  extra?: readonly (ArtifactReference | null | undefined)[];
}) {
  const references = [...names.map((name) => mission.artifactIndex.get(name)
    ?? getEvidence(mission, name as MissionEvidenceName)?.reference), ...extra];
  const unique = new Map(references.flatMap((reference) => reference ? [[reference.path, reference] as const] : []));
  if (!unique.size) return <p className="cabin-detail-note">No original-artifact link is recorded for this panel.</p>;
  return <footer className="cabin-detail-evidence"><h3>Original recorded evidence</h3><ul>{[...unique.values()].map((reference) => <li key={reference.path}>
    <a href={missionRelativeUrl(mission.baseUrl, reference.path)} target="_blank" rel="noreferrer">{reference.path.split("/").at(-1)}</a>
  </li>)}</ul></footer>;
}

function BookLink({ id, onOpenBook }: { id: StageBookId; onOpenBook: Props["onOpenBook"] }) {
  if (!onOpenBook) return null;
  const name = id[0].toUpperCase() + id.slice(1);
  return <button className="cabin-detail-book-link" type="button" onClick={() => onOpenBook(id)}>Read the {name} ledger</button>;
}

function hasReadOnlyMandate(mission: MissionViewModel): boolean {
  const exactWarnings = ["READ_ONLY_DATA_RUN_NO_TRADING_AUTHORITY", "Mandate is valid but does not permit action: READ_ONLY_DATA_RUN_NO_TRADING_AUTHORITY"];
  if (mission.warnings.some((value) => exactWarnings.includes(value))) return true;
  return (["council_synthesis", "governor_rendered_decision", "governor_decision"] as const).some((name) => {
    const document = getEvidenceDocument(mission, name);
    return ["blockers", "blocking_reasons"].some((key) => getStringArray(document?.[key])?.includes("mandate:READ_ONLY_DATA_RUN_NO_TRADING_AUTHORITY"));
  });
}

function Governance({ mission, onOpenBook }: Pick<Props, "mission" | "onOpenBook">) {
  const rendered = getEvidenceDocument(mission, "governor_rendered_decision");
  const noTrade = hasReadOnlyMandate(mission);
  return <>
    <p className="notice-lede">Completing a review is not the same as approving action.</p>
    <p>Technical status describes whether each process ran. Its native result describes the conclusion. The operator result and final mission outcome are separate records.</p>
    {noTrade ? <p className="cabin-detail-boundary">This mission records an explicit analysis-only mandate with no trading authority. Its action restriction is a recorded blocker, not evidence that Council or Governor software failed.</p> : null}
    <Facts rows={[
      ["Council process", `${processLabel(mission.stages.council.technicalStatus)} · ${mission.stages.council.technicalStatus}`],
      ["Council native result", mission.stages.council.nativeState],
      ["Governor process", `${processLabel(mission.stages.governor.technicalStatus)} · ${mission.stages.governor.technicalStatus}`],
      ["Governor native result", mission.stages.governor.nativeState],
      ["Mission's Governor disposition", mission.status.governorDisposition],
      ["Rendered decision artifact", getString(rendered?.disposition) ?? MISSING],
      ["Recorded next step", getString(rendered?.allowed_next_step) === "NONE" ? "None — no onward action authorized by this decision" : getString(rendered?.allowed_next_step) ?? MISSING],
      ["Operator route", mission.status.operatorRoute], ["Operator result", mission.status.operatorResult],
      ["Mission outcome", mission.status.outcome],
    ]} />
    <p>Governor PROCEED alone is not mission approval. A blocked Council result can still reach Governor for review; it does not become permission to act.</p>
    <BookLink id="governor" onOpenBook={onOpenBook} />
    <BookLink id="council" onOpenBook={onOpenBook} />
    <EvidenceLinks mission={mission} names={["council_synthesis", "council_mandate_policy", "governor_rendered_decision", "operator_action"]} />
  </>;
}

function Portfolio({ mission }: Pick<Props, "mission">) {
  const snapshot = mission.portfolio.snapshot;
  if (!snapshot) return <>
    <p className="notice-lede">No read-only portfolio snapshot is attached to this mission.</p>
    <p>Holdings, cash, exposure, and account value are unknown here. Fleet symbols and the Navigator reference symbol are not evidence of positions.</p>
    <p>No illustrative holdings, allocations, or performance figures have been created.</p>
    <EvidenceLinks mission={mission} names={["portfolio_snapshot"]} />
  </>;
  const money = (value: number) => `${value.toLocaleString("en-US", { maximumFractionDigits: 8 })} ${snapshot.currency}`;
  const optionalRow = (label: string, value: number | undefined): Row[] => value === undefined ? [] : [[label, money(value)]];
  return <>
    <p className="notice-lede">Captured holdings—not a live account connection.</p>
    <Facts rows={[
      ["Source", snapshot.source_identity], ["Capture time", <Timestamp value={snapshot.captured_at} />],
      ["Recorded mode", snapshot.mode], ["Account type", snapshot.account_type], ["Currency", snapshot.currency],
      ["Supplied positions", snapshot.positions.length],
      ...optionalRow("Recorded cash", snapshot.cash), ...optionalRow("Recorded equity", snapshot.equity),
      ...optionalRow("Recorded total exposure", snapshot.total_exposure),
    ]} />
    <p>Only supplied fields appear below. Amounts use the snapshot's recorded currency. No totals, weights, returns, or missing values were calculated.</p>
    {snapshot.positions.length === 0 ? <p>The snapshot contains no position records.</p> : <div className="cabin-position-list">{snapshot.positions.map((position, index) => <section key={`${position.symbol}-${index}`} aria-label={`Captured position ${position.symbol}`}>
      <h3>{position.symbol}{position.name ? ` · ${position.name}` : ""}</h3>
      <Facts rows={[
        ...(position.quantity === undefined ? [] : [["Quantity", position.quantity] as Row]),
        ...optionalRow("Market value", position.market_value),
        ...(position.allocation_percent === undefined ? [] : [["Recorded allocation", `${position.allocation_percent}%`] as Row]),
        ...optionalRow("Cost basis", position.cost_basis), ...optionalRow("Unrealized P&L", position.unrealized_pnl),
      ]} />
      {Object.keys(position).every((key) => key === "symbol" || key === "name") ? <p>No quantity or valuation fields were supplied for this position.</p> : null}
    </section>)}</div>}
    <p className="cabin-detail-boundary">Viewing these records does not connect to a broker or authorize portfolio changes.</p>
    <EvidenceLinks mission={mission} names={["portfolio_snapshot"]} />
  </>;
}

const operationMeaning: Readonly<Record<string, string>> = {
  VALIDATE: "Check the supplied handoff and constraints.", PLAN_ONLY: "Prepare analysis only; do not execute it.",
  SUBMIT_ORDER: "Send a new order.", CANCEL_ORDER: "Cancel an order.", MODIFY_ORDER: "Change an order.",
  MODIFY_PORTFOLIO: "Change portfolio holdings.", BROKER_CALL: "Call a broker service.",
};

function Operations({ heading, values }: { heading: string; values: readonly string[] }) {
  return <section><h3>{heading}</h3>{values.length ? <ul className="cabin-operation-list">{values.map((value) => <li key={value}><code>{value}</code> — {Object.hasOwn(operationMeaning, value) ? operationMeaning[value] : "No plain-language interpretation is defined for this recorded operation."}</li>)}</ul> : <p>No operations are listed in this recorded category.</p>}</section>;
}

export function CabinPanelDetails({ panel, mission, onOpenBook, onOpenWatchlist, onOpenNavigator, onOpenReferenceTape }: Props) {
  const market = mission.market.navigatorMarket;
  const assessment = getEvidenceDocument(mission, "oracle_assessment");
  const interval = market ? ({ "1h": "Hourly", "1d": "Daily", "1wk": "Weekly" }[market.timeframe]) : MISSING;
  const marketLink = <EvidenceLinks mission={mission} names={[]} extra={[mission.market.artifactReference]} />;
  let content: ReactNode;
  switch (panel) {
    case "market": content = <>
      <p className="notice-lede">Oracle's market assessment and Navigator's symbol reference answer different questions.</p>
      <p>The mission symbol identifies this run. Oracle describes its measured fleet; Navigator supplies separate captured prices for the reference symbol.</p>
      <Facts rows={[["Mission symbol", mission.status.symbol], ["Navigator reference", market ? `${market.symbol} · ${market.name}` : "No captured reference attached"]]} />
      <section aria-label="Recorded Oracle assessment"><h3>Recorded Oracle assessment</h3><Facts rows={[
        ["Participation", explainRecordedCode(getString(assessment?.breadth_posture))],
        ["Leadership", explainRecordedCode(getString(assessment?.leadership_posture))],
        ["Sector rotation", explainRecordedCode(getString(assessment?.rotation_posture))],
        ["Risk posture", explainRecordedCode(getString(assessment?.risk_regime_posture))],
      ]} /></section>
      <p>These descriptions do not establish the outlook for one security or provide permission to trade.</p>
      <BookLink id="oracle" onOpenBook={onOpenBook} />
      <EvidenceLinks mission={mission} names={["oracle_assessment", "oracle_report"]} extra={[mission.market.artifactReference]} />
    </>; break;
    case "fleet":
    case "watchlist": content = <>
      {panel === "watchlist" ? <LocalWatchlist mission={mission} /> : onOpenWatchlist ? <>
        <button type="button" className="cabin-detail-book-link" onClick={onOpenWatchlist}>Manage local watchlist</button>
        <p className="cabin-detail-note">Your browser-only watchlist is separate from the captured fleet below.</p>
      </> : null}
      <Facts rows={[["Mission outcome", mission.status.outcome], ["Current phase", mission.status.currentPhase], ["Mission symbol", mission.status.symbol]]} />
      <FleetOverview mission={mission} onOpenNavigator={onOpenNavigator} onOpenReferenceTape={onOpenReferenceTape} />
      {panel === "watchlist" ? <section aria-label="Mission warnings"><h3>Mission warnings</h3><MissionWarnings warnings={mission.warnings} /></section> : null}
      <BookLink id="oracle" onOpenBook={onOpenBook} />
    </>; break;
    case "modeldock": content = <>
      <p className="notice-lede">The model call recorded for this mission—not a current health check.</p>
      <p>These values describe the saved inference and its provenance. Opening this panel does not contact ModelDock, test a model, or request new commentary.</p>
      <Facts rows={[
        ["Recorded status", mission.modeldock.status], ["Recorded mode", mission.modeldock.mode],
        ["Provider", mission.modeldock.provider], ["Model", mission.modeldock.model],
        ["Trace ID", mission.modeldock.traceId], ["Service identity", mission.modeldock.serviceIdentity],
        ["Model revision", mission.modeldock.modelRevision],
        ["Recorded latency", mission.modeldock.latencyMs === null ? MISSING : `${mission.modeldock.latencyMs} ms`],
        ["Last successful inference in this record", <Timestamp value={mission.modeldock.lastSuccessfulInference} />],
        ["Mocked", mission.modeldock.mocked === null ? MISSING : mission.modeldock.mocked ? "Yes" : "No"],
        ["Mission-time provenance", mission.modeldock.availability],
      ]} />
      <p>{mission.modeldock.roleStatement}</p>
      <BookLink id="oracle" onOpenBook={onOpenBook} />
      <EvidenceLinks mission={mission} names={["oracle_modeldock_provenance", "oracle_modeldock_narrative"]} />
    </>; break;
    case "timeframe": content = <>
      <p className="notice-lede">Price bars and mission snapshots are different kinds of observations.</p>
      <Facts rows={[
        ["Original chart bar interval", market ? `${interval} · ${market.timeframe}` : MISSING],
        ["Original supplied price bars", market?.points.length ?? MISSING],
        ["Original supplied moving average", market ? `MA${market.ma_period} · ${market.ma_period} bars` : MISSING],
        ["Mission snapshots", mission.status.snapshotCount],
      ]} />
      <p>A price bar describes one supplied market interval. A mission snapshot records a workflow state; it is not another price sample.</p>
      <p>Navigator's interval choices come only from attached captured datasets. This panel does not acquire finer bars or calculate a new moving average.</p>
      {marketLink}
    </>; break;
    case "mission": content = <>
      <p className="notice-lede">The saved mission currently displayed in the Cabin.</p>
      <Facts rows={[
        ["Mission ID", mission.status.missionId], ["Request ID", mission.status.requestId],
        ["Mission symbol", mission.status.symbol], ["Run mode", mission.status.runMode],
        ["Outcome", mission.status.outcome], ["Phase", mission.status.currentPhase],
        ["Terminal state", mission.status.terminal ? "Yes" : "No"],
        ["Resumable in the recorded workflow", mission.status.resumable ? "Yes" : "No"],
        ["Record source", mission.baseUrl], ["Final snapshot SHA-256", mission.status.finalSnapshotSha256],
      ]} />
      <p>The fingerprint identifies the recorded snapshot; it is not a confidence score. A terminal state does not necessarily mean approval. This panel cannot start or resume a mission.</p>
      <BookLink id="harbormaster" onOpenBook={onOpenBook} />
      <EvidenceLinks mission={mission} names={["mission_request", "mission_snapshot", "mission_summary"]} />
    </>; break;
    case "market-timing": content = <>
      <p className="notice-lede">When the reference was saved is separate from the time of its latest bar.</p>
      <Facts rows={[
        ["Capture time", <Timestamp value={mission.market.capturedAt} />],
        ["Latest supplied bar timestamp", <Timestamp value={mission.market.latestCompletedBar} />],
        ["Recorded market status", mission.market.marketStatus], ["Capture source", mission.market.sourceIdentity],
        ["Bar interval", market ? `${interval} · ${market.timeframe}` : MISSING],
      ]} />
      <p>A bar timestamp identifies its supplied interval. Capture time identifies the saved response. A missing market-status value does not imply that a market is open or closed.</p>
      <p>This is not a streaming quote. Refreshing the display does not acquire new price bars.</p>
      {market ? <NavigatorMarketProvenance market={market} /> : <p>No market capture is attached.</p>}
      {marketLink}
    </>; break;
    case "mission-time": content = <>
      <p className="notice-lede">Three timestamps describe the saved workflow—not the current market.</p>
      <Facts rows={[
        ["Mission started", <Timestamp value={mission.status.startedAt} />],
        ["Snapshot observed", <Timestamp value={mission.status.observedAt} />],
        ["Summary generated", <Timestamp value={mission.status.generatedAt} />],
      ]} />
      <p>Started marks mission initialization; observed belongs to the saved snapshot; generated belongs to the presentation summary. These times need not match the market capture or latest price bar.</p>
      <details className="recorded-details"><summary>Exact recorded timestamps</summary><Facts rows={[["Started", mission.status.startedAt], ["Observed", mission.status.observedAt], ["Generated", mission.status.generatedAt]]} /></details>
      <BookLink id="harbormaster" onOpenBook={onOpenBook} />
      <EvidenceLinks mission={mission} names={["mission_request", "mission_snapshot", "mission_summary"]} />
    </>; break;
    case "approval": content = <>
      <p className="notice-lede">Only explicitly recorded authority is shown.</p>
      <Facts rows={[["Approval scope", mission.status.approvalScope], ["Operator route", mission.status.operatorRoute], ["Operator result", mission.status.operatorResult], ["Governor disposition", mission.status.governorDisposition], ["Mission outcome", mission.status.outcome]]} />
      <p>Missing scope or operator results stay unrecorded. A successful process, PROCEED disposition, or visible price chart does not substitute for an operator approval.</p>
      <p className="cabin-detail-boundary">Even an approved Navigator handoff is limited to SHADOW validation and planning. This read-only Cabin cannot approve or execute anything.</p>
      <BookLink id="navigator" onOpenBook={onOpenBook} />
      <EvidenceLinks mission={mission} names={["operator_action", "operator_receipt", "navigator_handoff_envelope"]} />
    </>; break;
    case "governance":
    case "governor": content = <Governance mission={mission} onOpenBook={onOpenBook} />; break;
    case "portfolio": content = <Portfolio mission={mission} />; break;
    case "model-routing": content = <>
      <p className="notice-lede">ModelDock supplies narrative, not decision authority.</p>
      <p>Oracle remains authoritative for facts, measurements, diagnostics, and readiness. Recorded model commentary is an explanatory supplement; it does not replace those artifacts or grant permission to act.</p>
      <Facts rows={[["Recorded model mode", mission.modeldock.mode], ["Recorded provider", mission.modeldock.provider], ["Recorded model", mission.modeldock.model], ["Narrative status", mission.modeldock.status]]} />
      <p>The Cabin displays saved routing provenance. It cannot choose a model, route a new request, or call a provider.</p>
      <BookLink id="oracle" onOpenBook={onOpenBook} />
      <EvidenceLinks mission={mission} names={["oracle_report", "oracle_modeldock_narrative", "oracle_modeldock_provenance"]} />
    </>; break;
    case "safety": content = <>
      <p className="notice-lede">{mission.safety.displayStatement}</p>
      <p>These are the recorded operation boundaries, not evidence that a handoff was approved. This panel contains no execution controls.</p>
      <Operations heading="Allowed by the safety envelope" values={mission.safety.allowedOperations} />
      <Operations heading="Prohibited by the safety envelope" values={mission.safety.prohibitedOperations} />
      <details className="recorded-details"><summary>Exact recorded declaration</summary><code>{mission.safety.declaration}</code></details>
      <BookLink id="navigator" onOpenBook={onOpenBook} />
      <EvidenceLinks mission={mission} names={["navigator_handoff_envelope", "navigator_shadow_plan"]} />
    </>; break;
  }
  return <div className={`cabin-panel-details cabin-panel-details-${panel}`}>{content}</div>;
}
