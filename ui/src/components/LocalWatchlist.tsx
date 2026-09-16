import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { createRecordedFleetOverview, ORACLE_COVERAGE_LABELS } from "../data/fleetOverview";
import { hasNavigatorCapture } from "../data/navigatorSelection";
import { changeLocalWatchlist, LOCAL_WATCHLIST_KEY, MAX_LOCAL_WATCHLIST_SYMBOLS, readLocalWatchlist } from "../data/localWatchlist";
import type { MissionViewModel } from "../data/viewModel";
import "./local-watchlist.css";

type WatchlistStorage = Pick<Storage, "getItem" | "setItem">;
type Props = { mission: MissionViewModel; storage?: WatchlistStorage | null };

function browserStorage(): WatchlistStorage | null {
  try { return window.localStorage; } catch { return null; }
}

/** Local UI preferences only. Mission evidence is never a watchlist seed or write target. */
export function LocalWatchlist({ mission, storage }: Props) {
  const [saved, setSaved] = useState(() => readLocalWatchlist(storage === undefined ? browserStorage() : storage));
  const [input, setInput] = useState("");
  const [feedback, setFeedback] = useState("");
  const [invalidInput, setInvalidInput] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const retryRef = useRef<HTMLButtonElement>(null);
  const id = useId();
  const fleet = createRecordedFleetOverview(mission);
  const blocked = saved.status !== "ready";
  const previouslyBlocked = useRef(blocked);

  useEffect(() => {
    if (blocked && !previouslyBlocked.current
      && (document.activeElement === document.body || document.activeElement?.matches(":disabled"))) {
      retryRef.current?.focus();
    } else if (!blocked && previouslyBlocked.current && document.activeElement === document.body) {
      inputRef.current?.focus();
    }
    previouslyBlocked.current = blocked;
  }, [blocked]);

  useEffect(() => {
    const refresh = (event: StorageEvent) => {
      if (event.key !== null && event.key !== LOCAL_WATCHLIST_KEY) return;
      const target = storage === undefined ? browserStorage() : storage;
      if (event.storageArea && event.storageArea !== target) return;
      const next = readLocalWatchlist(target);
      setSaved((previous) => next.status === "ready" ? next : { ...next, symbols: previous.symbols });
      setFeedback(next.status === "ready" ? "Local watchlist updated from browser storage." : "");
    };
    window.addEventListener("storage", refresh);
    return () => window.removeEventListener("storage", refresh);
  }, [storage]);

  const retry = () => {
    const next = readLocalWatchlist(storage === undefined ? browserStorage() : storage);
    setSaved((previous) => next.status === "ready" ? next : { ...next, symbols: previous.symbols });
    setFeedback(next.status === "ready" ? "Local watchlist loaded from browser storage." : "");
  };

  const change = (type: "add" | "remove", symbol: string) => {
    const result = changeLocalWatchlist(storage === undefined ? browserStorage() : storage, { type, symbol });
    setFeedback(result.message);
    setInvalidInput(type === "add" && result.status === "invalid-symbol");
    if (result.status === "storage-error" || result.status === "invalid-data") {
      setSaved((previous) => ({ status: result.status as "storage-error" | "invalid-data", symbols: previous.symbols, message: result.message }));
    } else {
      setSaved({ status: "ready", symbols: result.symbols, message: "" });
    }
    if (result.status === "saved" || result.status === "unchanged") {
      if (type === "add") setInput("");
      inputRef.current?.focus();
    }
  };

  const add = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!blocked) change("add", input);
  };

  return <section className="local-watchlist" aria-labelledby={`${id}-title`}>
    <h3 id={`${id}-title`}>Local watchlist</h3>
    <p>Keep your own list of symbols. Saved only in this browser at this address—not synced to an account or other devices.</p>
    <p className="local-watchlist-boundary">Adding a symbol does not fetch prices, change the Navigator chart, or change the fleet used by analysis runs. Mission evidence and trading permissions stay unchanged.</p>
    <form onSubmit={add} aria-label="Add to local watchlist">
      <label htmlFor={`${id}-symbol`}>Symbol</label>
      <div className="local-watchlist-entry">
        <input ref={inputRef} id={`${id}-symbol`} value={input} disabled={blocked}
          onChange={(event) => { setInput(event.target.value); setInvalidInput(false); }}
          aria-describedby={`${id}-hint ${id}-feedback`} aria-invalid={invalidInput || undefined}
          autoComplete="off" autoCapitalize="characters" spellCheck={false} placeholder="e.g. AAPL or BRK.B" />
        <button type="submit" disabled={blocked}>Add symbol</button>
      </div>
      <p id={`${id}-hint`} className="local-watchlist-note">Up to {MAX_LOCAL_WATCHLIST_SYMBOLS} symbols, 20 characters each. Entries are unverified labels, not new Harbor members or holdings.</p>
    </form>
    <p id={`${id}-feedback`} role="status" aria-live="polite" aria-atomic="true" className="local-watchlist-feedback">{blocked ? saved.message : feedback}</p>
    {blocked ? <div className="local-watchlist-error">
      <p>Editing is paused. This editor has not replaced saved data. {saved.symbols.length > 0 ? "The list below is the last successfully loaded version; changes have not been saved." : "The saved list cannot currently be read or updated."}</p>
      <button ref={retryRef} type="button" onClick={retry}>Retry reading local watchlist</button>
    </div> : null}
    <p className="local-watchlist-count">{saved.symbols.length} of {MAX_LOCAL_WATCHLIST_SYMBOLS} local symbols{blocked ? " · last loaded" : ""}</p>
    {saved.symbols.length === 0 ? <p>{blocked ? "No readable local list to display." : "Your local watchlist is empty. Add a symbol above to begin."}</p> : <ul className="local-watchlist-symbols" aria-label="Local watchlist symbols">
      {saved.symbols.map((symbol) => {
        const row = fleet.rows.find((item) => item.symbol === symbol);
        const navigator = hasNavigatorCapture(mission, symbol);
        return <li key={symbol}>
          <div><strong>{symbol}</strong>
            {navigator ? <p>Navigator capture available in this mission.</p> : null}
            {row ? <p>{fleet.source === "normalized" ? "Recorded in the captured fleet" : "Recorded in analytical evidence"} · {ORACLE_COVERAGE_LABELS[row.coverage]}.</p> : null}
            {!row && !navigator ? <p>No captured fleet or Navigator evidence for this symbol in this mission.</p> : null}
          </div>
          <button type="button" disabled={blocked} onClick={() => change("remove", symbol)} aria-label={`Remove ${symbol} from local watchlist`}>Remove</button>
        </li>;
      })}
    </ul>}
    <details className="local-watchlist-storage"><summary>About this saved list</summary>
      <p>This list starts empty and stays separate from whichever mission you view. Evidence labels describe only the currently displayed mission; they do not validate a ticker or promise new data.</p>
      <p>Storage belongs to this browser and site address, including its port. Using localhost instead of 127.0.0.1, another port, or another browser gives you a separate list. Clearing site data removes it; private browsing may not retain it.</p>
      <p>Other tabs at the same address share the list. Avoid editing simultaneously in multiple tabs.</p>
    </details>
  </section>;
}
