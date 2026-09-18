import { useCallback, useEffect, useRef, useState } from "react";
import type { SentryResearchFeed } from "../contracts/sentryResearch";
import { loadSentryResearchFeed } from "./sentryResearchFeed";

export const SENTRY_RESEARCH_TIMEOUT_MS = 10_000;
export interface SentryResearchState {
  status: "LOADING" | "READY" | "UNAVAILABLE" | "NOT_CONFIGURED" | "DISABLED";
  feed: SentryResearchFeed | null; message: string; refreshing: boolean; refresh: () => void;
}

/** One fixed read on opening/manual refresh; no polling or provider requests. */
export function useSentryResearchFeed({ enabled }: { enabled: boolean }): SentryResearchState {
  const [state, setState] = useState<Omit<SentryResearchState, "refresh">>({ status: "DISABLED", feed: null, message: "Research archive reading is paused.", refreshing: false });
  const [attempt, setAttempt] = useState(0);
  const lastCheck = useRef<number | null>(null);
  const refresh = useCallback(() => setAttempt((value) => value + 1), []);
  useEffect(() => {
    if (!enabled || document.visibilityState !== "visible") {
      setState((prior) => ({ ...prior, status: "DISABLED", refreshing: false, message: "Research archive reading is paused. Open the live ledger and refresh to read saved evidence." }));
      return;
    }
    let active = true, paused = false;
    const controller = new AbortController();
    const onVisibility = () => {
      if (document.visibilityState !== "visible") {
        paused = true; controller.abort();
        setState((prior) => ({ ...prior, status: "DISABLED", refreshing: false, message: "Reading paused while the page was hidden. Refresh to check the archive again." }));
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    const timer = setTimeout(() => controller.abort(), SENTRY_RESEARCH_TIMEOUT_MS);
    let abort: (() => void) | undefined;
    setState((prior) => ({ ...prior, status: prior.feed ? prior.status : "LOADING", refreshing: true }));
    void Promise.race([
      loadSentryResearchFeed({ signal: controller.signal }),
      new Promise<never>((_, reject) => { abort = () => reject(new Error("Research read cancelled.")); controller.signal.addEventListener("abort", abort, { once: true }); }),
    ]).then((feed) => {
      if (!active || paused || controller.signal.aborted) return;
      const checked = Date.parse(feed.checked_at);
      if (lastCheck.current !== null && checked < lastCheck.current) throw new Error("Research reader receipt is out of order.");
      lastCheck.current = checked;
      setState((prior) => ({ status: feed.status, feed: feed.status === "READY" ? feed : prior.feed, message: feed.message, refreshing: false }));
    }).catch(() => {
      if (!active || paused) return;
      setState((prior) => ({ ...prior, status: "UNAVAILABLE", refreshing: false,
        message: prior.feed ? "Research checkpoint could not be refreshed. The last verified archive remains below; its current availability is unconfirmed." : "No research checkpoint could be verified." }));
    }).finally(() => { clearTimeout(timer); if (abort) controller.signal.removeEventListener("abort", abort); });
    return () => { active = false; controller.abort(); clearTimeout(timer); document.removeEventListener("visibilitychange", onVisibility); };
  }, [enabled, attempt]);
  return { ...state, refresh };
}
