import { NAVIGATOR_MARKET_CONTRACT, type NavigatorMarket } from "../contracts/cabinContext";
import { NAVIGATOR_FLEET_CATALOG_SCHEMA, type NavigatorFleetCatalogEntry, type NavigatorFleetCatalogV1 } from "../contracts/navigatorFleetCatalog";
import type { ArtifactReference } from "../contracts/presentation";
import { asJsonObject, parseArtifactReference, PresentationContractError } from "./validate";
import type { CabinMissionCorrelation } from "./validateCabinContext";

const SYMBOL = /^[A-Z][A-Z0-9.-]{0,19}$/;
const TIMEFRAMES = ["1h", "1d", "1wk"] as const;
const MA_PERIODS = [20, 50, 100, 200, 250] as const;
const RFC3339 = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
const REFERENCE_KEYS = ["name", "path", "sha256", "producer", "byte_size", "schema_version", "observed_at"] as const;

function exactKeys(value: Record<string, unknown>, expected: readonly string[], label: string): void {
  if (Object.keys(value).length !== expected.length || expected.some((key) => !Object.hasOwn(value, key))) {
    throw new PresentationContractError(`${label} has invalid fields`);
  }
}

function text(value: unknown, label: string, max = 256): string {
  if (typeof value !== "string" || !value || value.trim() !== value || value.length > max || /[\u0000-\u001f\u007f-\u009f]/.test(value)) {
    throw new PresentationContractError(`${label} must be supported nonblank trimmed text`);
  }
  return value;
}

function timestamp(value: unknown, label: string): string {
  const parsed = text(value, label);
  const parts = RFC3339.exec(parsed);
  const instant = Date.parse(parsed);
  if (!parts || Number.isNaN(instant)) throw new PresentationContractError(`${label} must be an RFC 3339 timestamp`);
  const [, year, month, day, hour, minute, second] = parts.map(Number);
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const monthDays = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  const utcYear = new Date(instant).getUTCFullYear();
  // Date.parse rolls February 31 and 24:00 into another day. Match the
  // canonical Python calendar/range checks without changing supplied text.
  if (year < 1 || month < 1 || month > 12 || day < 1 || day > monthDays[month - 1]
    || hour > 23 || minute > 59 || second > 59 || utcYear < 1 || utcYear > 9999) {
    throw new PresentationContractError(`${label} must be a valid calendar timestamp`);
  }
  return parsed;
}

function reference(value: unknown, label: string): ArtifactReference {
  exactKeys(asJsonObject(value, label), REFERENCE_KEYS, label);
  const parsed = parseArtifactReference(value, label);
  if (parsed.byte_size === null || !Number.isSafeInteger(parsed.byte_size)) throw new PresentationContractError(`${label} requires a safe byte size`);
  if (parsed.observed_at !== null) timestamp(parsed.observed_at, `${label} observed_at`);
  return parsed;
}

/** Strict membership proof for captures; unlike overview rendering, no fallback rows qualify. */
export function navigatorFleetObservedSymbols(value: unknown): ReadonlySet<string> {
  const snapshot = asJsonObject(value, "Navigator fleet normalized snapshot");
  if (!Array.isArray(snapshot.symbols) || snapshot.symbols.length < 1 || snapshot.symbols.length > 100) {
    throw new PresentationContractError("Navigator fleet normalized snapshot requires 1 to 100 observed members");
  }
  const members = new Set<string>();
  for (const value of snapshot.symbols) {
    const row = asJsonObject(value, "Navigator fleet observed member");
    const symbol = text(row.symbol, "Navigator fleet observed symbol", 20);
    if (!SYMBOL.test(symbol) || members.has(symbol)) throw new PresentationContractError("Navigator fleet observed symbols must be supported and unique");
    members.add(symbol);
  }
  if (Object.hasOwn(snapshot, "symbol_count") && (!Number.isSafeInteger(snapshot.symbol_count) || snapshot.symbol_count !== members.size)) {
    throw new PresentationContractError("Navigator fleet normalized snapshot symbol count conflicts with observed members");
  }
  return members;
}

/** Publication-bound datasets only: no watchlist membership, data acquisition, or derived indicators. */
export function parseNavigatorFleetCatalog(
  value: unknown,
  expected: CabinMissionCorrelation,
  expectedFleetReference: ArtifactReference,
  verifiedFleetDocument: unknown,
  originalMarket?: Pick<NavigatorMarket, "symbol"> | null,
): NavigatorFleetCatalogV1 {
  const catalog = asJsonObject(value, "Navigator fleet catalog");
  exactKeys(catalog, ["schema_version", "mission_id", "request_id", "mission_symbol", "run_mode", "captured_at", "fleet_snapshot", "navigator_source", "entries"], "Navigator fleet catalog");
  if (catalog.schema_version !== NAVIGATOR_FLEET_CATALOG_SCHEMA) throw new PresentationContractError("unsupported Navigator fleet catalog schema");
  const missionId = text(catalog.mission_id, "Navigator fleet mission_id", 128);
  const requestId = text(catalog.request_id, "Navigator fleet request_id", 128);
  const missionSymbol = text(catalog.mission_symbol, "Navigator fleet mission_symbol", 64);
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(missionId) || !/^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$/.test(requestId)
    || catalog.run_mode !== "LIVE" || expected.run_mode !== "LIVE" || missionId !== expected.mission_id || requestId !== expected.request_id || missionSymbol !== expected.symbol) {
    throw new PresentationContractError("Navigator fleet catalog conflicts with canonical LIVE mission correlation");
  }
  const capturedAt = timestamp(catalog.captured_at, "Navigator fleet catalog captured_at");
  const fleetReference = reference(catalog.fleet_snapshot, "Navigator fleet snapshot reference");
  if (fleetReference.name !== "oracle_normalized_snapshot" || REFERENCE_KEYS.some((key) => fleetReference[key] !== expectedFleetReference[key])) {
    throw new PresentationContractError("Navigator fleet catalog snapshot reference conflicts with canonical indexed evidence");
  }
  const members = navigatorFleetObservedSymbols(verifiedFleetDocument);
  const source = asJsonObject(catalog.navigator_source, "Navigator fleet source");
  exactKeys(source, ["git_revision", "backend_sha256", "worktree_dirty"], "Navigator fleet source");
  const revision = text(source.git_revision, "Navigator fleet source revision");
  const backendSha = text(source.backend_sha256, "Navigator fleet source backend hash");
  if (!/^[0-9a-f]{40}$/.test(revision) || !/^[0-9a-f]{64}$/.test(backendSha) || typeof source.worktree_dirty !== "boolean") {
    throw new PresentationContractError("Navigator fleet source must record exact revision, backend SHA-256 and dirty-worktree flag");
  }
  if (!Array.isArray(catalog.entries) || catalog.entries.length < 1 || catalog.entries.length > 1500) throw new PresentationContractError("Navigator fleet catalog requires 1 to 1500 entries");
  const triples = new Set<string>();
  const entries: NavigatorFleetCatalogEntry[] = catalog.entries.map((value, index) => {
    const label = `Navigator fleet entry ${index}`;
    const entry = asJsonObject(value, label);
    exactKeys(entry, ["symbol", "timeframe", "ma_period", "captured_at", "transport", "source_identity", "artifact"], label);
    const symbol = text(entry.symbol, `${label} symbol`, 20);
    if (!SYMBOL.test(symbol) || !members.has(symbol)) throw new PresentationContractError(`${label} symbol is not a supported observed fleet member`);
    if (originalMarket && symbol === expected.symbol) throw new PresentationContractError(`${label} may not replace the original mission-symbol captures`);
    if (!TIMEFRAMES.includes(entry.timeframe as NavigatorMarket["timeframe"]) || typeof entry.ma_period !== "number" || !MA_PERIODS.includes(entry.ma_period as NavigatorMarket["ma_period"])) {
      throw new PresentationContractError(`${label} timeframe/MA is unsupported`);
    }
    const timeframe = entry.timeframe as NavigatorMarket["timeframe"];
    const maPeriod = entry.ma_period as NavigatorMarket["ma_period"];
    const triple = `${symbol}-${timeframe}-ma${maPeriod}`;
    if (triples.has(triple)) throw new PresentationContractError(`${label} duplicates a symbol/timeframe/MA capture`);
    triples.add(triple);
    const observedAt = timestamp(entry.captured_at, `${label} captured_at`);
    if (entry.transport !== "HTTP" && entry.transport !== "LOCAL_JSON") throw new PresentationContractError(`${label} transport is unsupported`);
    const identity = text(entry.source_identity, `${label} source_identity`);
    if (!/^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$/.test(identity)) throw new PresentationContractError(`${label} source identity must be opaque, not a path`);
    const artifact = reference(entry.artifact, `${label} artifact`);
    if (artifact.name !== "navigator_fleet_market" || artifact.producer !== "navigator" || artifact.path !== `presentation/navigator_fleet/${triple}.json`
      || artifact.schema_version !== NAVIGATOR_MARKET_CONTRACT || artifact.observed_at !== observedAt) {
      throw new PresentationContractError(`${label} artifact is inconsistent`);
    }
    return { symbol, timeframe, ma_period: maPeriod, captured_at: observedAt, transport: entry.transport, source_identity: identity, artifact };
  });
  return {
    schema_version: NAVIGATOR_FLEET_CATALOG_SCHEMA, mission_id: missionId, request_id: requestId, mission_symbol: missionSymbol,
    run_mode: "LIVE", captured_at: capturedAt, fleet_snapshot: fleetReference,
    navigator_source: { git_revision: revision, backend_sha256: backendSha, worktree_dirty: source.worktree_dirty }, entries,
  };
}
