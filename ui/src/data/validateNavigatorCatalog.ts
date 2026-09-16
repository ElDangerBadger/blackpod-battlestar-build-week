import { NAVIGATOR_MARKET_CONTRACT, type NavigatorMarket } from "../contracts/cabinContext";
import {
  NAVIGATOR_CATALOG_SCHEMA,
  type NavigatorCatalogEntry,
  type NavigatorCatalogV1,
} from "../contracts/navigatorCatalog";
import type { CabinMissionCorrelation } from "./validateCabinContext";
import { asJsonObject, parseArtifactReference, PresentationContractError } from "./validate";

const TIMEFRAMES = ["1h", "1d", "1wk"] as const;
const MA_PERIODS = [20, 50, 100, 200, 250] as const;
const RFC3339 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

function exactKeys(value: Record<string, unknown>, expected: readonly string[], label: string): void {
  if (Object.keys(value).length !== expected.length || expected.some((key) => !Object.hasOwn(value, key))) {
    throw new PresentationContractError(`${label} has invalid fields`);
  }
}

function text(value: unknown, label: string, maxLength = 256): string {
  if (typeof value !== "string" || !value || value.trim() !== value || value.length > maxLength
    || [...value].some((character) => character.codePointAt(0)! < 32)) {
    throw new PresentationContractError(`${label} must be supported nonblank trimmed text`);
  }
  return value;
}

function timestamp(value: unknown, label: string): string {
  const parsed = text(value, label);
  if (!RFC3339.test(parsed) || Number.isNaN(Date.parse(parsed))) {
    throw new PresentationContractError(`${label} must be an RFC 3339 timestamp`);
  }
  return parsed;
}

/** No indicator calculations, inferred intervals, or fallback datasets. */
export function parseNavigatorCatalog(
  value: unknown,
  expected: CabinMissionCorrelation,
  defaultMarket: Pick<NavigatorMarket, "timeframe" | "ma_period">,
): NavigatorCatalogV1 {
  const item = asJsonObject(value, "Navigator catalog");
  exactKeys(item, ["schema_version", "mission_id", "request_id", "symbol", "run_mode", "captured_at", "entries"], "Navigator catalog");
  if (item.schema_version !== NAVIGATOR_CATALOG_SCHEMA) {
    throw new PresentationContractError("unsupported Navigator catalog schema");
  }
  const missionId = text(item.mission_id, "Navigator catalog mission_id", 128);
  const requestId = text(item.request_id, "Navigator catalog request_id", 128);
  const symbol = text(item.symbol, "Navigator catalog symbol", 64);
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(missionId)
    || !/^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$/.test(requestId)) {
    throw new PresentationContractError("Navigator catalog correlation identifiers are invalid");
  }
  if (item.run_mode !== "LIVE" || expected.run_mode !== "LIVE"
    || missionId !== expected.mission_id || requestId !== expected.request_id || symbol !== expected.symbol) {
    throw new PresentationContractError("Navigator catalog conflicts with canonical LIVE mission correlation");
  }
  const capturedAt = timestamp(item.captured_at, "Navigator catalog captured_at");
  if (!Array.isArray(item.entries) || item.entries.length < 1 || item.entries.length > 15) {
    throw new PresentationContractError("Navigator catalog requires 1 to 15 entries");
  }
  const pairs = new Set<string>();
  const entries: NavigatorCatalogEntry[] = item.entries.map((value, index) => {
    const label = `Navigator catalog entry ${index}`;
    const entry = asJsonObject(value, label);
    exactKeys(entry, ["timeframe", "ma_period", "captured_at", "transport", "source_identity", "navigator_git_revision", "artifact"], label);
    if (!TIMEFRAMES.includes(entry.timeframe as NavigatorMarket["timeframe"])) {
      throw new PresentationContractError(`${label} timeframe is unsupported`);
    }
    if (typeof entry.ma_period !== "number" || !MA_PERIODS.includes(entry.ma_period as NavigatorMarket["ma_period"])) {
      throw new PresentationContractError(`${label} ma_period is unsupported`);
    }
    const timeframe = entry.timeframe as NavigatorMarket["timeframe"];
    const maPeriod = entry.ma_period as NavigatorMarket["ma_period"];
    const pair = `${timeframe}-ma${maPeriod}`;
    if (pairs.has(pair) || (timeframe === defaultMarket.timeframe && maPeriod === defaultMarket.ma_period)) {
      throw new PresentationContractError(`${label} duplicates a captured timeframe/MA pair`);
    }
    pairs.add(pair);
    const entryCapturedAt = timestamp(entry.captured_at, `${label} captured_at`);
    if (entry.transport !== "HTTP" && entry.transport !== "LOCAL_JSON") {
      throw new PresentationContractError(`${label} transport is unsupported`);
    }
    const sourceIdentity = text(entry.source_identity, `${label} source_identity`);
    if (!/^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$/.test(sourceIdentity)) {
      throw new PresentationContractError(`${label} source_identity must be an opaque identity, not a path`);
    }
    const revision = text(entry.navigator_git_revision, `${label} navigator_git_revision`);
    if (!/^[0-9a-f]{40}$/.test(revision)) {
      throw new PresentationContractError(`${label} navigator_git_revision must be 40 lowercase hexadecimal characters`);
    }
    const artifact = parseArtifactReference(entry.artifact, `${label} artifact`);
    if (artifact.name !== "navigator_market_variant" || artifact.producer !== "navigator"
      || artifact.path !== `presentation/navigator_variants/${pair}.json`
      || artifact.schema_version !== NAVIGATOR_MARKET_CONTRACT || artifact.byte_size === null
      || !Number.isSafeInteger(artifact.byte_size) || artifact.observed_at !== entryCapturedAt) {
      throw new PresentationContractError(`${label} artifact is inconsistent`);
    }
    return {
      timeframe, ma_period: maPeriod, captured_at: entryCapturedAt, transport: entry.transport,
      source_identity: sourceIdentity, navigator_git_revision: revision, artifact,
    };
  });
  return {
    schema_version: NAVIGATOR_CATALOG_SCHEMA, mission_id: missionId, request_id: requestId,
    symbol, run_mode: "LIVE", captured_at: capturedAt, entries,
  };
}
