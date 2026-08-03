import type { OhlcResponse, TickerInfo, Timeframe, MaPeriod } from '../types';

function resolveApiBase(): string {
  // 1. Explicit override always wins.
  if (import.meta.env.VITE_API_BASE) return import.meta.env.VITE_API_BASE;
  if (typeof window === 'undefined') return 'http://localhost:8000';

  const { hostname, origin } = window.location;

  // 2. e2b preview: backend is the same host on the 8000- subdomain.
  if (hostname.includes('e2b.app')) {
    return origin.replace(/^https?:\/\/\d+-/, 'https://8000-');
  }

  // 3. Local dev: Vite (3000) talks to uvicorn (8000).
  if (hostname === 'localhost' || hostname === '127.0.0.1') {
    return 'http://localhost:8000';
  }

  // 4. Production: the FastAPI app serves the built frontend from the
  //    same origin, so use relative requests.
  return '';
}

const API_BASE = resolveApiBase();

export async function fetchTickers(): Promise<TickerInfo[]> {
  const r = await fetch(`${API_BASE}/api/tickers`);
  if (!r.ok) throw new Error(`tickers: ${r.status}`);
  return r.json();
}

export async function fetchOhlc(
  symbol: string,
  timeframe: Timeframe,
  ma: MaPeriod,
): Promise<OhlcResponse> {
  const url = `${API_BASE}/api/ohlc?symbol=${symbol}&timeframe=${timeframe}&ma=${ma}`;
  const r = await fetch(url);
  if (!r.ok) {
    const text = await r.text().catch(() => '');
    throw new Error(`ohlc ${r.status}: ${text}`);
  }
  return r.json();
}