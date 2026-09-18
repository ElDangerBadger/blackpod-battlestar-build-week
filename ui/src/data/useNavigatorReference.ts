import { useEffect, useRef, useState } from "react";
import type { NavigatorReferenceSelection, NavigatorReferenceSnapshot, NavigatorReferenceStatus } from "../contracts/navigatorReference";
import { loadNavigatorReference, navigatorReferenceStatus, navigatorReferenceUrl, NAVIGATOR_REFERENCE_INTERVAL_MS, NAVIGATOR_REFERENCE_TIMEOUT_MS } from "./navigatorReference";

export interface NavigatorReferenceState {
  identity: string | null;
  status: NavigatorReferenceStatus | "LOADING";
  snapshot: NavigatorReferenceSnapshot | null;
  checkedAt: string | null;
  message: string;
}
const empty = (identity: string | null): NavigatorReferenceState => ({ identity, status: "LOADING", snapshot: null, checkedAt: null, message: "Checking the current completed-bar reference." });

/** One selected, same-origin reference; no provider calls or browser MA math. */
export function useNavigatorReference({ publicationId, selection, enabled }: {
  publicationId: string | null; selection: NavigatorReferenceSelection | null; enabled: boolean;
}): NavigatorReferenceState {
  const url = navigatorReferenceUrl(publicationId, selection);
  const [state, setState] = useState<NavigatorReferenceState>(() => empty(url));
  const accepted = useRef<{ identity: string; checkedAt: string; snapshot: NavigatorReferenceSnapshot | null } | null>(null);
  useEffect(() => {
    if (!enabled || !url || !selection) return;
    let disposed = false;
    let busy = false;
    let controller: AbortController | null = null;
    let timeout: ReturnType<typeof setTimeout> | null = null;
    let expiry: ReturnType<typeof setTimeout> | null = null;
    const expire = (snapshot: NavigatorReferenceSnapshot | null) => {
      if (expiry !== null) clearTimeout(expiry);
      if (!snapshot) return;
      const delay = Date.parse(snapshot.valid_until) - Date.now();
      if (delay <= 0) return;
      expiry = setTimeout(() => {
        if (!disposed) setState((value) => value.identity === url && value.snapshot?.snapshot_id === snapshot.snapshot_id ? { ...value, status: "STALE" } : value);
      }, Math.min(delay, 2_147_483_647));
    };
    const poll = async () => {
      if (disposed || busy) return;
      busy = true;
      controller = new AbortController();
      timeout = setTimeout(() => controller?.abort(), NAVIGATOR_REFERENCE_TIMEOUT_MS);
      try {
        const feed = await loadNavigatorReference(url, selection, controller.signal);
        if (disposed) return;
        const previous = accepted.current?.identity === url ? accepted.current : null;
        if (previous && Date.parse(feed.checked_at) < Date.parse(previous.checkedAt)) throw new Error("Reference time moved backward");
        if (previous?.snapshot && feed.snapshot && Date.parse(feed.snapshot.captured_at) < Date.parse(previous.snapshot.captured_at)) throw new Error("Reference capture moved backward");
        const snapshot = previous?.snapshot && (feed.snapshot === null || previous.snapshot.snapshot_id === feed.snapshot.snapshot_id)
          ? previous.snapshot : feed.snapshot;
        accepted.current = { identity: url, checkedAt: feed.checked_at, snapshot };
        setState({ identity: url, snapshot, checkedAt: feed.checked_at, message: feed.message, status: navigatorReferenceStatus(feed.status, snapshot) });
        expire(snapshot);
      } catch {
        if (!disposed) setState((value) => ({
          ...(value.identity === url ? value : empty(url)),
          status: value.identity === url && value.snapshot ? "STALE" : "UNAVAILABLE",
          message: "Current reference unavailable. Any retained reference is not current; saved mission evidence remains available.",
        }));
      } finally {
        if (timeout !== null) clearTimeout(timeout);
        busy = false;
      }
    };
    void poll();
    const interval = setInterval(() => { void poll(); }, NAVIGATOR_REFERENCE_INTERVAL_MS);
    return () => {
      disposed = true;
      controller?.abort();
      clearInterval(interval);
      if (timeout !== null) clearTimeout(timeout);
      if (expiry !== null) clearTimeout(expiry);
    };
  }, [url, enabled]); // Identity includes the entire selected pair, not object identity.
  if (state.identity !== url) return empty(url);
  return state.snapshot && Date.parse(state.snapshot.valid_until) <= Date.now() ? { ...state, status: "STALE" } : state;
}
