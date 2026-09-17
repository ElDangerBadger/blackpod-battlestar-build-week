import { useCallback, useEffect, useRef, useState } from "react";
import type { SentryFeed } from "../contracts/sentry";
import { loadSentryFeed, sentryFeedIsOlder } from "./sentryFeed";

export const SENTRY_POLL_MS = 15_000;
export const SENTRY_REQUEST_TIMEOUT_MS = 10_000;
export interface SentryFeedState {
  status: "LOADING" | "READY" | "NOT_CONFIGURED" | "UNAVAILABLE" | "DISABLED";
  /** Last verified READY feed, retained and visibly unavailable when a refresh fails. */
  feed: SentryFeed | null;
  message: string;
  refreshing: boolean;
  refresh: () => void;
}

/** Only the expanded LIVE ledger enables this hook. Research age is never refreshed away. */
export function useSentryFeed({ enabled }: { enabled: boolean }): SentryFeedState {
  const [state, setState] = useState<Omit<SentryFeedState, "refresh">>({ status: "DISABLED", feed: null,
    message: "Sentry archive following is paused.", refreshing: false });
  const latest = useRef<SentryFeed | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [visible, setVisible] = useState(() => document.visibilityState === "visible");
  const refresh = useCallback(() => setAttempt((value) => value + 1), []);

  useEffect(() => {
    const onVisibility = () => setVisible(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  useEffect(() => {
    if (!enabled || !visible) {
      setState((prior) => ({ ...prior, status: "DISABLED", refreshing: false,
        message: !enabled ? "Sentry archive following is paused." : "Sentry archive following pauses while this window is hidden." }));
      return;
    }
    let active = true;
    let controller: AbortController | undefined;
    let nextPoll: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      controller = new AbortController();
      const signal = controller.signal;
      setState((prior) => ({ ...prior, status: prior.feed ? prior.status : "LOADING", refreshing: true }));
      let rejectAbort: (() => void) | undefined;
      const timeout = setTimeout(() => controller?.abort(), SENTRY_REQUEST_TIMEOUT_MS);
      try {
        const feed = await Promise.race([
          loadSentryFeed({ signal }),
          new Promise<never>((_, reject) => {
            rejectAbort = () => reject(new Error("Sentry archive request cancelled."));
            signal.addEventListener("abort", rejectAbort, { once: true });
          }),
        ]);
        if (!active || signal.aborted) return;
        if (latest.current && sentryFeedIsOlder(feed, latest.current)) throw new Error("Sentry archive receipt is out of order.");
        latest.current = feed;
        setState((prior) => ({ status: feed.status, feed: feed.status === "READY" ? feed : prior.feed,
          message: feed.status !== "READY" && prior.feed
            ? `${feed.message} Showing the last verified archive; it has not been refreshed.` : feed.message,
          refreshing: false }));
      } catch {
        if (!active) return;
        setState((prior) => ({ ...prior, status: "UNAVAILABLE", refreshing: false,
          message: prior.feed ? "Sentry archive could not be refreshed. Showing the last verified archive; it may be outdated."
            : "Sentry archive is unavailable. No observations have been verified." }));
      } finally {
        clearTimeout(timeout);
        if (rejectAbort) signal.removeEventListener("abort", rejectAbort);
        if (active) nextPoll = setTimeout(poll, SENTRY_POLL_MS);
      }
    };
    void poll();
    return () => { active = false; clearTimeout(nextPoll); controller?.abort(); };
  }, [enabled, visible, attempt]);

  return { ...state, refresh };
}
