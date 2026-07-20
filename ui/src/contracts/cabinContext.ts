import type { ArtifactReference, RunMode } from "./presentation";

/** Read-only Stage 4 presentation supplements. These do not alter mission state. */
export const CABIN_CONTEXT_SCHEMA = "blackpod.cabin_context.v1" as const;
export const PORTFOLIO_SNAPSHOT_SCHEMA = "blackpod.portfolio_snapshot.v1" as const;
export const NAVIGATOR_MARKET_CONTRACT = "navigator.api.ohlc.v1" as const;

export type CaptureStatus = "CAPTURED" | "NOT_CONFIGURED";
export type CaptureTransport = "HTTP" | "LOCAL_JSON";
export type PortfolioMode = "FROZEN" | "LIVE";

export interface NavigatorMarketPoint {
  t: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
  ma: number | null;
  atr: number | null;
}

export interface NavigatorMarketSummary {
  last_price: number;
  last_ma: number | null;
  pct_vs_ma: number;
  position: "above" | "near" | "below";
  trend_slope_pct: number;
  volatility: "glass" | "gentle" | "moderate" | "high" | "storm";
  atr: number;
  atr_pct: number;
  ma_period: 20 | 50 | 100 | 200 | 250;
  bar_count: number;
}

export interface NavigatorMarket {
  symbol: string;
  name: string;
  category: "equity" | "index" | "commodity" | "crypto";
  timeframe: "1h" | "1d" | "1wk";
  ma_period: 20 | 50 | 100 | 200 | 250;
  currency: string;
  points: NavigatorMarketPoint[];
  summary: NavigatorMarketSummary;
}

export interface PortfolioPosition {
  symbol: string;
  name?: string;
  quantity?: number;
  market_value?: number;
  allocation_percent?: number;
  cost_basis?: number;
  unrealized_pnl?: number;
}

export interface PortfolioSnapshotV1 {
  schema_version: typeof PORTFOLIO_SNAPSHOT_SCHEMA;
  captured_at: string;
  source_identity: string;
  mode: PortfolioMode;
  account_type: string;
  currency: string;
  cash?: number;
  equity?: number;
  total_exposure?: number;
  positions: PortfolioPosition[];
}

export interface MarketCaptureProvenance {
  status: CaptureStatus;
  transport: CaptureTransport | null;
  source_identity: string | null;
  navigator_git_revision: string | null;
}

export interface PortfolioCaptureProvenance {
  status: CaptureStatus;
  transport: CaptureTransport | null;
  source_identity: string | null;
}

export interface CabinContextV1 {
  schema_version: typeof CABIN_CONTEXT_SCHEMA;
  mission_id: string;
  request_id: string;
  symbol: string;
  run_mode: RunMode;
  captured_at: string;
  market_artifact: ArtifactReference | null;
  portfolio_artifact: ArtifactReference | null;
  capture_provenance: {
    market: MarketCaptureProvenance;
    portfolio: PortfolioCaptureProvenance;
  };
}
