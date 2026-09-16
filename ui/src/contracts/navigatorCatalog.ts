import type { CaptureTransport, NavigatorMarket } from "./cabinContext";
import type { ArtifactReference } from "./presentation";

/** Additional exact Navigator captures; the original Cabin context stays unchanged. */
export const NAVIGATOR_CATALOG_SCHEMA = "blackpod.navigator_catalog.v1" as const;
export const NAVIGATOR_CATALOG_PATH = "presentation/navigator_catalog.json" as const;

export interface NavigatorCatalogEntry {
  timeframe: NavigatorMarket["timeframe"];
  ma_period: NavigatorMarket["ma_period"];
  captured_at: string;
  transport: CaptureTransport;
  source_identity: string;
  navigator_git_revision: string;
  artifact: ArtifactReference;
}

export interface NavigatorCatalogV1 {
  schema_version: typeof NAVIGATOR_CATALOG_SCHEMA;
  mission_id: string;
  request_id: string;
  symbol: string;
  run_mode: "LIVE";
  captured_at: string;
  entries: readonly NavigatorCatalogEntry[];
}

/** Only validated, publication-bound captures reach presentation controls. */
export interface NavigatorMarketVariant {
  market: NavigatorMarket;
  capturedAt: string;
  sourceIdentity: string;
  navigatorGitRevision: string;
  reference: ArtifactReference;
  /** Present only on source-attested multi-symbol fleet captures. */
  navigatorSourceSha256?: string;
  navigatorWorktreeDirty?: boolean;
}
