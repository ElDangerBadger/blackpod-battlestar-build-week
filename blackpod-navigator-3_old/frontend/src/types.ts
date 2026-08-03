export interface TickerInfo {
  symbol: string;
  name: string;
  category: 'equity' | 'index' | 'commodity' | 'crypto';
}

export interface Bar {
  t: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
  ma: number | null;
  atr: number | null;
}

export type Position = 'above' | 'near' | 'below';
export type Volatility = 'glass' | 'gentle' | 'moderate' | 'high' | 'storm';

export interface OhlcSummary {
  last_price: number;
  last_ma: number | null;
  pct_vs_ma: number;
  position: Position;
  trend_slope_pct: number;
  volatility: Volatility;
  atr: number;
  atr_pct: number;
  ma_period: number;
  bar_count: number;
}

export interface DataMeta {
  stale: boolean;
  age_seconds: number;
  source: string;
  provider: string;
}

export interface OhlcResponse {
  symbol: string;
  name: string;
  category: string;
  timeframe: string;
  ma_period: number;
  currency: string;
  disclaimer?: string;
  data?: DataMeta;
  points: Bar[];
  summary: OhlcSummary;
}

export type Timeframe = '1h' | '1d' | '1wk';
export type MaPeriod = 20 | 50 | 100 | 200 | 250;