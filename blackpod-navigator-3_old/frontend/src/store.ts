import { create } from 'zustand';
import { fetchOhlc, fetchTickers } from './lib/api';
import type { MaPeriod, OhlcResponse, TickerInfo, Timeframe } from './types';

interface MarketState {
  tickers: TickerInfo[];
  symbol: string;
  timeframe: Timeframe;
  maPeriod: MaPeriod;
  oceanExag: number; // 0..2, multiplies wake amplitude
  zoomT: number; // 0..1, target camera continuum (set by UI)
  viewT: number; // 0..1, *smoothed* camera continuum (written by CameraRig, throttled)
  data: OhlcResponse | null;
  loading: boolean;
  error: string | null;

  initTickers: () => Promise<void>;
  setSymbol: (s: string) => void;
  setTimeframe: (t: Timeframe) => void;
  setMaPeriod: (p: MaPeriod) => void;
  setOceanExag: (v: number) => void;
  setZoomT: (v: number) => void;
  setViewT: (v: number) => void;
  nudgeZoom: (delta: number) => void;
  fetch: () => Promise<void>;
}

export const useMarket = create<MarketState>((set, get) => ({
  tickers: [],
  symbol: 'SPY',
  timeframe: '1d',
  maPeriod: 200,
  oceanExag: 1,
  zoomT: 0.1,
  viewT: 0.1,
  data: null,
  loading: false,
  error: null,

  initTickers: async () => {
    try {
      const tickers = await fetchTickers();
      set({ tickers });
    } catch (e: unknown) {
      set({ error: (e as Error).message });
    }
  },

  setSymbol: (s) => {
    set({ symbol: s });
    void get().fetch();
  },
  setTimeframe: (t) => {
    set({ timeframe: t });
    void get().fetch();
  },
  setMaPeriod: (p) => {
    set({ maPeriod: p });
    void get().fetch();
  },
  setOceanExag: (v) => set({ oceanExag: v }),
  setZoomT: (v) => set({ zoomT: Math.max(0, Math.min(1, v)) }),
  setViewT: (v) => set({ viewT: Math.max(0, Math.min(1, v)) }),
  nudgeZoom: (delta) =>
    set((s) => ({ zoomT: Math.max(0, Math.min(1, s.zoomT + delta)) })),

  fetch: async () => {
    const { symbol, timeframe, maPeriod } = get();
    set({ loading: true, error: null });
    try {
      const data = await fetchOhlc(symbol, timeframe, maPeriod);
      set({ data, loading: false });
    } catch (e: unknown) {
      set({ error: (e as Error).message, loading: false });
    }
  },
}));