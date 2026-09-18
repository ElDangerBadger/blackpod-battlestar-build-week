import type { NavigatorMarket } from "./cabinContext";

export type NavigatorReferenceSelection = Pick<NavigatorMarket, "symbol" | "timeframe" | "ma_period">;
export type NavigatorReferenceStatus = "READY" | "STALE" | "UNAVAILABLE" | "NOT_CONFIGURED";
export interface NavigatorReferenceSnapshot extends NavigatorReferenceSelection {
  schema_version: "navigator.reference_snapshot.v1";
  snapshot_id: string;
  captured_at: string;
  provider_fetched_at: string;
  bar_policy: "completed_regular_session";
  latest_bar_at: number;
  expected_bar_at: number;
  valid_until: string;
  calendar_id: string;
  provider: "yfinance";
  adjustment: "auto_adjust=True";
  market: NavigatorMarket;
}
export interface NavigatorReferenceFeed {
  schema_version: "blackpod.navigator_reference_feed.v1";
  status: NavigatorReferenceStatus;
  checked_at: string;
  message: string;
  snapshot: NavigatorReferenceSnapshot | null;
}
export type NavigatorReferenceMode = "CURRENT" | "SAVED";
