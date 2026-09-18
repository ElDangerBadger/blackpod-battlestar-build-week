import type { NavigatorReferenceMode } from "../contracts/navigatorReference";
import type { NavigatorReferenceState } from "../data/useNavigatorReference";
import "./navigator-current-reference.css";

export function NavigatorCurrentReference({ state, mode, onModeChange }: {
  state: NavigatorReferenceState; mode: NavigatorReferenceMode; onModeChange: (mode: NavigatorReferenceMode) => void;
}) {
  const snapshot = state.snapshot;
  return <section className="navigator-current-reference" aria-label="Navigator history reference source">
    <div role="group" aria-label="Navigator history source">
      <button type="button" aria-pressed={mode === "CURRENT"} onClick={() => onModeChange("CURRENT")}>Current reference</button>
      <button type="button" aria-pressed={mode === "SAVED"} onClick={() => onModeChange("SAVED")}>Saved reference</button>
      <strong>{mode === "SAVED" ? "SAVED MISSION REFERENCE" : `CURRENT REFERENCE · ${state.status}`}</strong>
      {snapshot && mode === "CURRENT" ? <span>Latest completed bar: {new Date(snapshot.latest_bar_at * 1000).toISOString()}</span> : null}
    </div>
    {mode === "CURRENT" && (!snapshot || state.status !== "READY") ? <p role="status">{!snapshot ? "Showing the saved capture until a valid current reference is available." : "Retained reference is not current."}</p> : null}
    {mode === "SAVED" ? <p>Saved price history and moving average from the selected mission capture. Current-reference refresh is paused.</p> : null}
    <details><summary>Reference timing and provenance</summary>
      {mode === "CURRENT" ? <p>{state.message} {state.status === "READY" ? "Using the latest available completed regular-session bars." : ""}</p> : null}
      {snapshot && mode === "CURRENT" ? <p>Captured: {snapshot.captured_at} · provider fetched: {snapshot.provider_fetched_at} · valid until: {snapshot.valid_until} · snapshot: {snapshot.snapshot_id}.</p> : null}
      <p>Reference check: {state.checkedAt ?? "not yet"} · checks every minute while selected. A fresh check does not make an expired reference current.</p>
      <p>Completed-bar history and supplied moving average only · separate from the live trade-price overlay · does not update mission ledgers or create trade authority.</p>
    </details>
  </section>;
}
