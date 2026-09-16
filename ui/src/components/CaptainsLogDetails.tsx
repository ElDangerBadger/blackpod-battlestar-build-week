import { processLabel } from "../books/ledgerBriefings";
import { missionRelativeUrl } from "../data/loadMission";
import { isMissionRelativePath } from "../data/validate";
import type { CaptainLogEntryViewModel, MissionViewModel } from "../data/viewModel";
import "./captains-log-details.css";

const STAGE_LABELS: Readonly<Record<string, string>> = {
  HARBORMASTER: "Harbormaster · mission intake",
  ORACLE: "Oracle · market assessment",
  MODELDOCK: "ModelDock · recorded commentary",
  COUNCIL: "Council · combined review",
  GOVERNOR: "Governor · decision gate",
  OPERATOR: "Operator · recorded action",
  NAVIGATOR: "Navigator · SHADOW planning",
  MISSION: "Mission · recorded outcome",
};

const PROCESS_MEANINGS: Readonly<Record<string, string>> = {
  SUCCEEDED: "The process completed successfully. This is a processing result, not action approval.",
  FAILED: "The process is recorded as failed. Its exact recorded summary is available below; no cause is inferred here.",
  RUNNING: "The process was in progress at this recorded timestamp. This does not claim that it is running now.",
  NOT_STARTED: "The process is recorded as not started. That is not the same as a failed process.",
  SKIPPED: "The process is recorded as skipped. No reason is inferred beyond the saved summary.",
  NOT_RECORDED: "No process result is recorded for this entry. Missing evidence is not interpreted as success or failure.",
};

const OPERATOR_MEANINGS: Readonly<Record<string, string>> = {
  APPROVED_FOR_HANDOFF: "An operator approval for handoff is recorded. This is not approval to place an order or execute a trade.",
  REJECTED: "The operator recorded a rejection. No approved handoff is implied by this entry.",
  PENDING_APPROVAL: "The operator route is awaiting approval. Routing alone does not record an approval.",
  PENDING_REVIEW: "The operator route is awaiting review. Routing alone does not record an action.",
  CLOSED_BLOCKED: "The operator route is closed because action is blocked. This route does not record an approved handoff.",
  CLOSED_NO_ACTION: "The operator route is closed with no action. This does not record an approved handoff.",
};

const MISSION_MEANINGS: Readonly<Record<string, string>> = {
  APPROVED: "The mission outcome is recorded as approved, limited to its recorded approval scope. It is not an execution record.",
  HELD: "The mission outcome is recorded as held. A held outcome is separate from whether its individual processes completed successfully.",
  VETOED: "The mission outcome is recorded as vetoed. Its exact rationale remains in the recorded evidence.",
  FAILED: "The mission outcome is recorded as failed. The saved entries describe what was recorded; no additional cause is inferred.",
  INCOMPLETE: "The mission outcome is recorded as incomplete. This is the saved state, not a forecast of whether it will finish.",
};

function recordedTime(timestamp: string): string {
  const date = new Date(timestamp);
  if (!Number.isFinite(date.getTime())) return timestamp;
  return `${new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium", timeStyle: "medium", timeZone: "UTC",
  }).format(date)} UTC`;
}

function safeArtifactPath(path: string): boolean {
  return isMissionRelativePath(path)
    && !/[?#%\u0000-\u001f\u007f]/.test(path)
    && !/^[a-z][a-z0-9+.-]*:/i.test(path);
}

function explanation(entry: CaptainLogEntryViewModel): string {
  if (!Object.hasOwn(STAGE_LABELS, entry.stage)) {
    return "No plain-language interpretation is defined for this stage. Its recorded stage, status, and summary are preserved.";
  }
  const meanings = entry.stage === "MISSION" ? MISSION_MEANINGS
    : entry.stage === "OPERATOR" && Object.hasOwn(OPERATOR_MEANINGS, entry.status)
      ? OPERATOR_MEANINGS : PROCESS_MEANINGS;
  return Object.hasOwn(meanings, entry.status) ? meanings[entry.status]
    : "No plain-language interpretation is defined for this status. Its exact recorded value is preserved.";
}

function stageContext(entry: CaptainLogEntryViewModel, mission: MissionViewModel): string | null {
  switch (entry.stage) {
    case "HARBORMASTER": return "Harbormaster tracks mission intake and record integrity; it does not make a market decision.";
    case "ORACLE": return "Oracle describes the measured market universe. Its assessment does not recommend a trade in the selected symbol.";
    case "MODELDOCK": return "This is recorded model commentary. Oracle remains authoritative for measurements and readiness; opening this log does not request new inference.";
    case "COUNCIL": return `Council’s review result is separate from its process status. A completed review can still record a blocked result. Current recorded Council result: ${mission.stages.council.nativeState ?? "Not recorded"}.`;
    case "GOVERNOR": return `Governor’s decision is separate from process completion. Even PROCEED is not operator approval or permission to execute a trade. Current recorded Governor disposition: ${mission.status.governorDisposition ?? "Not recorded"}.`;
    case "OPERATOR": return "Only an explicitly recorded operator result establishes whether a handoff was approved. This read-only log cannot record an action.";
    case "NAVIGATOR": return mission.status.navigatorPlanStatus === null
      ? "No operational SHADOW plan status is recorded. That absence alone is not a software failure; the separate market-reference chart may still be available."
      : `Current recorded SHADOW plan status: ${mission.status.navigatorPlanStatus}. A plan is not an executed order.`;
    default: return null;
  }
}

export function CaptainsLogDetails({ mission }: { mission: MissionViewModel }) {
  return <section className="captains-log-details" aria-label="Captain's Log details">
    <p className="captains-log-details-lede">Read the recorded mission sequence</p>
    <p>These entries retain their captured order. Process completion, review decisions, and operator approval are separate facts; <code>SUCCEEDED</code> does not itself grant permission to act.</p>
    <p className="captains-log-details-boundary">Read-only evidence. No mission is started, resumed, or approved here, and no order or trade is executed.</p>
    {mission.captainsLog.length === 0 ? <p>No Captain’s Log entries are recorded in the supplied mission.</p> : <ol className="captains-log-details-list">
      {mission.captainsLog.map((entry, index) => {
        const knownStage = Object.hasOwn(STAGE_LABELS, entry.stage);
        const title = knownStage ? STAGE_LABELS[entry.stage] : entry.stage;
        const context = stageContext(entry, mission);
        const label = knownStage && entry.stage !== "MISSION" ? processLabel(entry.status) : entry.status;
        const sourcePaths = [...new Set(entry.sourceArtifacts.map((artifact) => artifact.path))];
        const safeSourcePaths = sourcePaths.filter(safeArtifactPath);
        return <li key={`${index}-${entry.stage}-${entry.timestamp}`}>
          <article aria-label={title}>
            <header>
              <h3>{title}</h3>
              <p className="captains-log-details-status">{label} <span>· recorded status <code>{entry.status}</code></span></p>
            </header>
            <p>{explanation(entry)}</p>
            {context ? <p>{context}</p> : null}
            <dl className="captains-log-details-metadata">
              <div><dt>Recorded timestamp</dt><dd><time dateTime={entry.timestamp} title={entry.timestamp}>{recordedTime(entry.timestamp)}</time></dd></div>
              <div><dt>Supporting evidence</dt><dd>{entry.evidenceCount} {entry.evidenceCount === 1 ? "record" : "records"}</dd></div>
            </dl>
            <details className="captains-log-recorded-summary">
              <summary>Recorded summary · exact wording</summary>
              <p>{entry.summary}</p>
              <p className="captains-log-recorded-stage">Recorded stage: <code>{entry.stage}</code></p>
              <p className="captains-log-recorded-stage">Exact timestamp: <code>{entry.timestamp}</code></p>
              {safeSourcePaths.length > 0 ? <div className="captains-log-source-evidence">
                <p>Original recorded evidence</p>
                <ul>{safeSourcePaths.map((path) => <li key={path}>
                  <a href={missionRelativeUrl(mission.baseUrl, path)} target="_blank" rel="noreferrer">{path}</a>
                </li>)}</ul>
              </div> : <p className="captains-log-recorded-stage">No safe artifact links are available for this entry.</p>}
              {safeSourcePaths.length < sourcePaths.length ? <p className="captains-log-recorded-stage">Unsafe recorded artifact paths were not linked.</p> : null}
            </details>
          </article>
        </li>;
      })}
    </ol>}
  </section>;
}
