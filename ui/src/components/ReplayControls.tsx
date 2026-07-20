import type { ReplaySpeed, ReplayTheater } from "../replay/useReplayTheater";

type ReplayControlsProps = {
  theater: ReplayTheater;
  announcement: string;
};

export function ReplayControls({ theater, announcement }: ReplayControlsProps) {
  const complete = theater.revealCount === 8;

  return (
    <aside className="replay-theater" aria-label="Mission replay theater">
      <span className="replay-label">Mission replay</span>
      <button type="button" onClick={theater.isPlaying ? theater.pause : theater.play}>
        {theater.isPlaying ? "Pause" : complete ? "Play again" : "Play"}
      </button>
      <button type="button" onClick={theater.restart}>Restart</button>
      <button type="button" onClick={theater.stepForward} disabled={complete}>
        Step
      </button>
      <label>
        <span className="sr-only">Replay speed</span>
        <select
          aria-label="Replay speed"
          value={theater.speed}
          onChange={(event) => theater.setSpeed(Number(event.target.value) as ReplaySpeed)}
        >
          <option value={0.5}>0.5×</option>
          <option value={1}>1×</option>
          <option value={2}>2×</option>
        </select>
      </label>
      <span className="replay-progress" aria-hidden="true">
        {theater.revealCount}/8
      </span>
      <span className="sr-only" aria-live="polite">{announcement}</span>
    </aside>
  );
}
