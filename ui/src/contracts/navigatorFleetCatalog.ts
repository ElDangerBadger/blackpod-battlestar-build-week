import type { CaptureTransport, NavigatorMarket } from "./cabinContext";
import type { ArtifactReference } from "./presentation";

export const NAVIGATOR_FLEET_CATALOG_SCHEMA = "blackpod.navigator_fleet_catalog.v1" as const;
export const NAVIGATOR_FLEET_CATALOG_PATH = "presentation/navigator_fleet_catalog.json" as const;

export interface NavigatorFleetSource {
  git_revision: string;
  backend_sha256: string;
  worktree_dirty: boolean;
}

export interface NavigatorFleetCatalogEntry {
  symbol: string;
  timeframe: NavigatorMarket["timeframe"];
  ma_period: NavigatorMarket["ma_period"];
  captured_at: string;
  transport: CaptureTransport;
  source_identity: string;
  artifact: ArtifactReference;
}

export interface NavigatorFleetCatalogV1 {
  schema_version: typeof NAVIGATOR_FLEET_CATALOG_SCHEMA;
  mission_id: string;
  request_id: string;
  mission_symbol: string;
  run_mode: "LIVE";
  captured_at: string;
  fleet_snapshot: ArtifactReference;
  navigator_source: NavigatorFleetSource;
  entries: readonly NavigatorFleetCatalogEntry[];
}
