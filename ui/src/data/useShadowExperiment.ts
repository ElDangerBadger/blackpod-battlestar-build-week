import { useCallback, useEffect, useRef, useState } from "react";
import type { ShadowExperimentFeed } from "../contracts/shadowExperiment";
import { loadShadowExperiment } from "./shadowExperiment";

export const SHADOW_EXPERIMENT_TIMEOUT_MS = 10_000;
export interface ShadowExperimentState {
  status: "LOADING" | "READY" | "UNAVAILABLE" | "NOT_CONFIGURED" | "DISABLED";
  feed: ShadowExperimentFeed | null;
  message: string;
  refreshing: boolean;
  refresh: () => void;
}

/** Read on open/manual refresh only. No polling, collection, or outcome creation. */
export function useShadowExperiment({ enabled }: { enabled: boolean }): ShadowExperimentState {
  const [state, setState] = useState<Omit<ShadowExperimentState, "refresh">>({
    status: "DISABLED", feed: null, message: "Experiment reading is paused.", refreshing: false,
  });
  const [attempt, setAttempt] = useState(0);
  const lastCheck = useRef<number | null>(null);
  const refresh = useCallback(() => setAttempt((value) => value + 1), []);
  useEffect(() => {
    if (!enabled || document.visibilityState !== "visible") {
      setState({ status: "DISABLED", feed: null, message: "Experiment reading is paused. Open the view and refresh to read saved records.", refreshing: false });
      return;
    }
    let active = true, paused = false;
    const controller = new AbortController();
    const onVisibility = () => {
      if (document.visibilityState !== "visible") {
        paused = true; controller.abort();
        setState({ status: "DISABLED", feed: null, refreshing: false, message: "Reading paused while the page was hidden. Refresh to check saved records again." });
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    const timer = setTimeout(() => controller.abort(), SHADOW_EXPERIMENT_TIMEOUT_MS);
    let abort: (() => void) | undefined;
    setState((prior) => ({ ...prior, status: prior.feed ? prior.status : "LOADING", refreshing: true }));
    void Promise.race([
      loadShadowExperiment({ signal: controller.signal }),
      new Promise<never>((_, reject) => { abort = () => reject(new Error("Experiment read cancelled.")); controller.signal.addEventListener("abort", abort, { once: true }); }),
    ]).then((feed) => {
      if (!active || paused || controller.signal.aborted) return;
      const checked = Date.parse(feed.checked_at);
      if (lastCheck.current !== null && checked < lastCheck.current) throw new Error("Experiment reader receipt is out of order.");
      lastCheck.current = checked;
      setState({ status: feed.status, feed: feed.status === "READY" ? feed : null, message: feed.message, refreshing: false });
    }).catch(() => {
      if (!active || paused) return;
      // Fail closed rather than presenting a prior prediction set as current.
      setState({ status: "UNAVAILABLE", feed: null, refreshing: false, message: "No saved experiment could be read and validated. No substitute predictions or outcomes are shown." });
    }).finally(() => { clearTimeout(timer); if (abort) controller.signal.removeEventListener("abort", abort); });
    return () => { active = false; controller.abort(); clearTimeout(timer); document.removeEventListener("visibilitychange", onVisibility); };
  }, [enabled, attempt]);
  return { ...state, refresh };
}
