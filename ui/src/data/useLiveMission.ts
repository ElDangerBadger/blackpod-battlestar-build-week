import { useEffect, useRef, useState } from "react";

import { loadLiveMissionBundle, loadLiveMissionFeed } from "./liveMission";
import { createMissionViewModel, type MissionViewModel } from "./viewModel";

export const LIVE_POLL_MS = 5_000;
export const LIVE_REQUEST_TIMEOUT_MS = 10_000;
/** A verified fleet publication can include hundreds of independently hashed captures. */
export const LIVE_BUNDLE_TIMEOUT_MS = 60_000;
export const EVIDENCE_STALE_MS = 15 * 60_000;

export interface LiveMissionState {
  status: "LOADING" | "READY" | "NOT_CONFIGURED" | "UNAVAILABLE";
  mission: MissionViewModel | null;
  message: string;
  checkedAt: string | null;
  verifiedAt: string | null;
  refreshing: boolean;
}

/** Follow only the reader's pinned mission. A failed refresh never replaces verified evidence. */
export function useLiveMission() {
  const [state, setState] = useState<LiveMissionState>({
    status: "LOADING", mission: null, message: "Connecting to the read-only mission reader.",
    checkedAt: null, verifiedAt: null, refreshing: true,
  });
  const publication = useRef<{ id: string; missionId: string; observedAt: string } | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    let nextPoll: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;
    const poll = async () => {
      controller = new AbortController();
      const signal = controller.signal;
      setState((prior) => ({ ...prior, refreshing: true }));
      let rejectAbort: (() => void) | undefined;
      let timeout = setTimeout(() => controller?.abort(), LIVE_REQUEST_TIMEOUT_MS);
      try {
        const result = await Promise.race([
          (async () => {
            const feed = await loadLiveMissionFeed({ signal });
            if (signal.aborted) throw new Error("Mission reader request cancelled.");
            if (feed.status === "READY" && publication.current?.id === feed.publication_id
              && (publication.current.missionId !== feed.mission_id || publication.current.observedAt !== feed.observed_at)) {
              throw new Error("Live feed identity differs from its verified publication.");
            }
            let mission: MissionViewModel | null = null;
            if (feed.status === "READY" && publication.current?.id !== feed.publication_id) {
              clearTimeout(timeout);
              timeout = setTimeout(() => controller?.abort(), LIVE_BUNDLE_TIMEOUT_MS);
              mission = createMissionViewModel(await loadLiveMissionBundle(feed, { signal }));
              if (signal.aborted) throw new Error("Mission reader request cancelled.");
            }
            return { feed, mission };
          })(),
          new Promise<never>((_, reject) => {
            rejectAbort = () => reject(new Error("Mission reader request timed out or was cancelled."));
            signal.addEventListener("abort", rejectAbort, { once: true });
          }),
        ]);
        if (!active) return;
        const { feed, mission } = result;
        if (feed.status === "READY") publication.current = {
          id: feed.publication_id, missionId: feed.mission_id, observedAt: feed.observed_at,
        };
        setState((prior) => ({
          status: feed.status,
          mission: mission ?? prior.mission,
          message: feed.message,
          checkedAt: feed.checked_at,
          verifiedAt: feed.status === "READY" ? new Date().toISOString() : prior.verifiedAt,
          refreshing: false,
        }));
      } catch (error) {
        if (!active) return;
        setState((prior) => ({ ...prior, status: "UNAVAILABLE", refreshing: false,
          message: error instanceof Error ? error.message : "Mission reader unavailable." }));
      } finally {
        clearTimeout(timeout);
        if (rejectAbort) signal.removeEventListener("abort", rejectAbort);
        if (active) nextPoll = setTimeout(poll, LIVE_POLL_MS);
      }
    };
    void poll();
    return () => {
      active = false;
      clearTimeout(nextPoll);
      controller?.abort();
    };
  }, [attempt]);

  return { ...state, refresh: () => setAttempt((value) => value + 1) };
}

export function evidenceFreshness(observedAt: string, now = Date.now()): string {
  const elapsed = now - Date.parse(observedAt);
  if (!Number.isFinite(elapsed)) return "EVIDENCE TIME UNKNOWN";
  if (elapsed < -60_000) return "EVIDENCE CLOCK AHEAD";
  return elapsed > EVIDENCE_STALE_MS ? "STALE EVIDENCE" : "RECENT EVIDENCE";
}
