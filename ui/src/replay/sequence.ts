export const REPLAY_SEQUENCE = [
  "HARBORMASTER",
  "ORACLE",
  "MODELDOCK",
  "COUNCIL",
  "GOVERNOR",
  "OPERATOR",
  "NAVIGATOR",
  "MISSION",
] as const;

export type ReplayStage = (typeof REPLAY_SEQUENCE)[number];

export const REPLAY_INTERVAL_MS = 2200;

export function clampRevealCount(value: number): number {
  return Math.min(REPLAY_SEQUENCE.length, Math.max(0, Math.trunc(value)));
}

export function revealedStages(count: number): readonly ReplayStage[] {
  return REPLAY_SEQUENCE.slice(0, clampRevealCount(count));
}
