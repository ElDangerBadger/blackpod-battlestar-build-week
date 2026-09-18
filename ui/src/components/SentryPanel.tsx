import { useId, useRef, useState, type KeyboardEvent } from "react";
import type { MissionViewModel } from "../data/viewModel";
import { SentryLedger } from "./SentryLedger";
import { SentryResearchLedger } from "./SentryResearchLedger";
import { SentryScanLedger } from "./SentryScanLedger";
import "./sentry-research.css";

export function SentryPanel({ enabled, mission, onOpenNavigator }: {
  enabled: boolean; mission: MissionViewModel; onOpenNavigator: (symbol: string) => void;
}) {
  const [tab, setTab] = useState(0);
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const id = useId();
  const choose = (next: number) => { setTab(next); buttons.current[next]?.focus(); };
  const keyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault(); choose(event.key === "Home" ? 0 : event.key === "End" ? 2 : (tab + (event.key === "ArrowRight" ? 1 : 2)) % 3);
  };
  return <div className="sentry-panel">
    <div role="tablist" aria-label="Sentry evidence views" className="sentry-panel-tabs">
      {["Microcap", "Sentry Research", "Scan results"].map((label, index) => <button key={label} ref={(node) => { buttons.current[index] = node; }} type="button"
        role="tab" id={`${id}-tab-${index}`} aria-controls={`${id}-panel-${index}`} aria-selected={tab === index}
        tabIndex={tab === index ? 0 : -1} onClick={() => setTab(index)} onKeyDown={keyDown}>{label}</button>)}
    </div>
    <div role="tabpanel" id={`${id}-panel-${tab}`} aria-labelledby={`${id}-tab-${tab}`}>
      {tab === 0 ? <SentryLedger enabled={enabled} mission={mission} onOpenNavigator={onOpenNavigator} /> : tab === 1 ? <SentryResearchLedger enabled={enabled} /> : <SentryScanLedger enabled={enabled} />}
    </div>
  </div>;
}
