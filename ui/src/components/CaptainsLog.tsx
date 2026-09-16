export type CaptainsLogEntryView = {
  stage: string;
  status: string;
  timestamp: string;
  summary: string;
  evidenceCount: number;
};

type CaptainsLogProps = {
  entries: readonly CaptainsLogEntryView[];
  revealedStages: ReadonlySet<string>;
  focused?: boolean;
  onFocus?: () => void;
};

export function CaptainsLog({ entries, revealedStages, focused, onFocus }: CaptainsLogProps) {
  return (
    <section className={`captains-log-copy captains-log-preview${onFocus ? " is-interactive" : ""}${focused ? " is-focused" : ""}`} aria-label="Captain's Log">
      <h3 className="panel-heading-button">
        <span>Captain’s Log</span>
        {onFocus ? <small className="captains-log-open-cue" aria-hidden="true">Open ↗</small> : null}
      </h3>
      <ol>
        {entries.map((entry) => {
          const revealed = revealedStages.has(entry.stage);
          return (
            <li key={`${entry.stage}-${entry.timestamp}`} className={revealed ? "is-revealed" : "is-concealed"}>
              <time dateTime={entry.timestamp}>{formatMissionTime(entry.timestamp)}</time>
              <div>
                <strong>{entry.stage}</strong>
                <span>{revealed ? entry.status : "Awaiting replay"}</span>
                {revealed ? <p>{entry.summary}</p> : null}
                {revealed ? <small>{entry.evidenceCount} evidence {entry.evidenceCount === 1 ? "record" : "records"}</small> : null}
              </div>
            </li>
          );
        })}
      </ol>
      {onFocus ? <button
        className="captains-log-paper-button"
        type="button"
        onClick={onFocus}
        aria-label="Focus Captain's Log"
        aria-haspopup="dialog"
        aria-expanded={focused}
      /> : null}
    </section>
  );
}

function formatMissionTime(timestamp: string): string {
  const match = timestamp.match(/T(\d{2}:\d{2})(?::\d{2}(?:\.\d+)?)?Z$/);
  return match?.[1] ?? timestamp;
}
import "./captains-log-details.css";
