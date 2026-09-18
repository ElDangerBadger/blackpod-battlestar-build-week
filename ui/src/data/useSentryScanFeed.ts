import { useCallback, useEffect, useRef, useState } from "react";
import type { SentryScanFeed } from "../contracts/sentryScan";
import { loadSentryScanFeed } from "./sentryScanFeed";

export const SENTRY_SCAN_TIMEOUT_MS = 10_000;
export interface SentryScanState {
  status: "LOADING" | "READY" | "UNAVAILABLE" | "NOT_CONFIGURED" | "DISABLED";
  feed: SentryScanFeed | null; message: string; refreshing: boolean; refresh: () => void;
}

/** Read saved receipts on open/manual refresh only. Never starts a scan. */
export function useSentryScanFeed({ enabled }: { enabled: boolean }): SentryScanState {
  const [state, setState] = useState<Omit<SentryScanState, "refresh">>({ status: "DISABLED", feed: null, message: "Scan receipt reading is paused.", refreshing: false });
  const [attempt, setAttempt] = useState(0);
  const lastCheck = useRef<number | null>(null);
  const refresh = useCallback(() => setAttempt((value) => value + 1), []);
  useEffect(() => {
    if (!enabled || document.visibilityState !== "visible") {
      setState((prior) => ({ ...prior, status: "DISABLED", refreshing: false, message: "Scan receipt reading is paused. Open the live ledger and refresh to read saved evidence." }));
      return;
    }
    let active = true, paused = false;
    const controller = new AbortController();
    const onVisibility = () => {
      if (document.visibilityState !== "visible") {
        paused = true; controller.abort();
        setState((prior) => ({ ...prior, status: "DISABLED", refreshing: false, message: "Reading paused while the page was hidden. Refresh to check saved scan records again." }));
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    const timer = setTimeout(() => controller.abort(), SENTRY_SCAN_TIMEOUT_MS);
    let abort: (() => void) | undefined;
    setState((prior) => ({ ...prior, status: prior.feed ? prior.status : "LOADING", refreshing: true }));
    void Promise.race([
      loadSentryScanFeed({ signal: controller.signal }),
      new Promise<never>((_, reject) => { abort = () => reject(new Error("Scan receipt read cancelled.")); controller.signal.addEventListener("abort", abort, { once: true }); }),
    ]).then((feed) => {
      if (!active || paused || controller.signal.aborted) return;
      const checked = Date.parse(feed.checked_at);
      if (lastCheck.current !== null && checked < lastCheck.current) throw new Error("Scan reader receipt is out of order.");
      lastCheck.current = checked;
      setState((prior) => ({ status: feed.status, feed: feed.status === "READY" ? feed : prior.feed, message: feed.message, refreshing: false }));
    }).catch(() => {
      if (!active || paused) return;
      setState((prior) => ({ ...prior, status: "UNAVAILABLE", refreshing: false,
        message: prior.feed ? "Scan records could not be refreshed. The last successfully read receipt remains below; its current availability is unconfirmed." : "No scan receipt could be read and validated." }));
    }).finally(() => { clearTimeout(timer); if (abort) controller.signal.removeEventListener("abort", abort); });
    return () => { active = false; controller.abort(); clearTimeout(timer); document.removeEventListener("visibilitychange", onVisibility); };
  }, [enabled, attempt]);
  return { ...state, refresh };
}
