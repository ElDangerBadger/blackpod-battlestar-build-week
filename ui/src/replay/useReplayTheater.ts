import { useCallback, useEffect, useMemo, useState } from "react";

import {
  REPLAY_INTERVAL_MS,
  REPLAY_SEQUENCE,
  clampRevealCount,
  revealedStages,
  type ReplayStage,
} from "./sequence";

export type ReplaySpeed = 0.5 | 1 | 2;

export type ReplayTheater = {
  isPlaying: boolean;
  revealCount: number;
  revealed: ReadonlySet<ReplayStage>;
  currentStage: ReplayStage | null;
  speed: ReplaySpeed;
  play: () => void;
  pause: () => void;
  restart: () => void;
  stepForward: () => void;
  setSpeed: (speed: ReplaySpeed) => void;
};

export function useReplayTheater(): ReplayTheater {
  // The cabin opens on the complete canonical mission. Restart enters theater mode.
  const [revealCount, setRevealCount] = useState<number>(REPLAY_SEQUENCE.length);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState<ReplaySpeed>(1);

  useEffect(() => {
    if (!isPlaying) return;
    if (revealCount >= REPLAY_SEQUENCE.length) {
      setIsPlaying(false);
      return;
    }

    const timer = window.setTimeout(() => {
      setRevealCount((count) => clampRevealCount(count + 1));
    }, REPLAY_INTERVAL_MS / speed);
    return () => window.clearTimeout(timer);
  }, [isPlaying, revealCount, speed]);

  const play = useCallback(() => {
    setRevealCount((count) => (count >= REPLAY_SEQUENCE.length ? 0 : count));
    setIsPlaying(true);
  }, []);

  const pause = useCallback(() => setIsPlaying(false), []);
  const restart = useCallback(() => {
    setRevealCount(0);
    setIsPlaying(false);
  }, []);
  const stepForward = useCallback(() => {
    setIsPlaying(false);
    setRevealCount((count) => clampRevealCount(count + 1));
  }, []);

  const stages = useMemo(() => revealedStages(revealCount), [revealCount]);
  const revealed = useMemo(() => new Set(stages), [stages]);
  const currentStage = revealCount > 0 ? REPLAY_SEQUENCE[revealCount - 1] : null;

  return {
    isPlaying,
    revealCount,
    revealed,
    currentStage,
    speed,
    play,
    pause,
    restart,
    stepForward,
    setSpeed,
  };
}
