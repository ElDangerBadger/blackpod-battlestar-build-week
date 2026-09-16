import { useEffect, useRef, useState } from "react";
import {
  LIVE_PRICE_MAX_AGE_MS, LIVE_PRICE_RETRY_MS, LIVE_PRICE_SILENCE_MS, liveNavigatorPriceUrl, livePriceStatus, validateLiveNavigatorPrice,
  type LiveNavigatorPriceEvent, type LiveNavigatorPriceStatus,
} from "./liveNavigatorPrice";

type State = Readonly<{
  identity: string;
  status: LiveNavigatorPriceStatus | "PAUSED";
  event: LiveNavigatorPriceEvent | null;
  quote: LiveNavigatorPriceEvent | null;
}>;

/** One ephemeral same-origin stream while the expanded LIVE Navigator is visible. */
export function useLiveNavigatorPrice({ publicationId, symbol, enabled }: {
  publicationId: string | null; symbol: string; enabled: boolean;
}) {
  const url = liveNavigatorPriceUrl(publicationId, symbol);
  const identity = `${publicationId ?? "none"}:${symbol}`;
  const [state, setState] = useState<State>({ identity, status: "PAUSED", event: null, quote: null });
  const accepted = useRef<{ identity: string; event: LiveNavigatorPriceEvent; quote: LiveNavigatorPriceEvent | null } | null>(null);

  useEffect(() => {
    let disposed = false;
    let source: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let watchdog: ReturnType<typeof setTimeout> | null = null;
    let expiry: ReturnType<typeof setTimeout> | null = null;
    let failures = 0;
    const update = (change: Partial<State>) => {
      if (!disposed) setState((current) => ({
        ...(current.identity === identity ? current : { identity, status: "PAUSED", event: null, quote: null }), ...change,
      }));
    };
    const close = () => {
      if (retry !== null) clearTimeout(retry);
      retry = null;
      if (watchdog !== null) clearTimeout(watchdog);
      watchdog = null;
      if (expiry !== null) clearTimeout(expiry);
      expiry = null;
      if (source) { source.onmessage = null; source.onerror = null; source.close(); }
      source = null;
    };
    const active = () => enabled && Boolean(url) && document.visibilityState !== "hidden";
    const unavailable = () => {
      close();
      update({ status: "UNAVAILABLE" });
      if (!disposed && active()) retry = setTimeout(connect, Math.min(30_000, LIVE_PRICE_RETRY_MS * 2 ** Math.min(failures++, 3)));
    };
    const connect = () => {
      close();
      if (!active()) { update({ status: "PAUSED" }); return; }
      if (typeof EventSource === "undefined") { update({ status: "UNAVAILABLE" }); return; }
      update({ status: "CONNECTING" });
      try {
        const current = new EventSource(url!);
        source = current;
        watchdog = setTimeout(unavailable, LIVE_PRICE_SILENCE_MS);
        current.onmessage = (message) => {
          if (disposed || source !== current || !active()) return;
          try {
            const previous = accepted.current?.identity === identity ? accepted.current : null;
            const event = validateLiveNavigatorPrice(JSON.parse(message.data), symbol, Date.now(), previous?.event);
            validateLiveNavigatorPrice(event, symbol, Date.now(), previous?.quote);
            accepted.current = { identity, event, quote: event.price !== null ? event : previous?.quote ?? null };
            failures = 0;
            if (watchdog !== null) clearTimeout(watchdog);
            watchdog = setTimeout(unavailable, LIVE_PRICE_SILENCE_MS);
            if (expiry !== null) clearTimeout(expiry);
            const status = livePriceStatus(event);
            if (status === "LIVE" && event.trade_at) expiry = setTimeout(() => update({ status: "STALE" }),
              Math.max(0, Date.parse(event.trade_at) + LIVE_PRICE_MAX_AGE_MS - Date.now()));
            update({ event, status, ...(event.price !== null ? { quote: event } : {}) });
          } catch { unavailable(); }
        };
        current.onerror = () => { if (!disposed && source === current) unavailable(); };
      } catch { unavailable(); }
    };
    const visibility = () => { if (active()) connect(); else { close(); update({ status: "PAUSED" }); } };
    connect();
    document.addEventListener("visibilitychange", visibility);
    return () => { disposed = true; close(); document.removeEventListener("visibilitychange", visibility); };
  }, [enabled, identity, symbol, url]);

  return state.identity === identity ? state : { identity, status: "CONNECTING" as const, event: null, quote: null };
}
