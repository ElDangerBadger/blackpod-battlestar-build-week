import {
  CABIN_CONTEXT_SCHEMA,
  NAVIGATOR_MARKET_CONTRACT,
  PORTFOLIO_SNAPSHOT_SCHEMA,
  type CabinContextV1,
  type CaptureStatus,
  type CaptureTransport,
  type NavigatorMarket,
  type NavigatorMarketPoint,
  type NavigatorMarketSummary,
  type PortfolioMode,
  type PortfolioPosition,
  type PortfolioSnapshotV1,
} from "../contracts/cabinContext";
import type { ArtifactReference, RunMode } from "../contracts/presentation";
import { parseArtifactReference, PresentationContractError } from "./validate";

const SHA256 = /^[0-9a-f]{64}$/;
const RFC3339 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$/;
const MISSION_ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/;
const SOURCE_IDENTITY = /^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$/;
const GIT_REVISION = /^[0-9a-f]{7,64}$/;
const CURRENCY = /^[A-Z]{3}$/;

const RUN_MODES = ["LIVE", "REPLAY"] as const;
const CAPTURE_STATUSES = ["CAPTURED", "NOT_CONFIGURED"] as const;
const CAPTURE_TRANSPORTS = ["HTTP", "LOCAL_JSON"] as const;
const PORTFOLIO_MODES = ["FROZEN", "LIVE"] as const;
const TIMEFRAMES = ["1h", "1d", "1wk"] as const;
const MA_PERIODS = [20, 50, 100, 200, 250] as const;
const MARKET_CATEGORIES = ["equity", "index", "commodity", "crypto"] as const;
const POSITIONS = ["above", "near", "below"] as const;
const VOLATILITY = ["glass", "gentle", "moderate", "high", "storm"] as const;

function objectValue(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new PresentationContractError(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function exactKeys(
  value: Record<string, unknown>,
  required: readonly string[],
  optional: readonly string[],
  label: string,
): void {
  const actual = Object.keys(value);
  const allowed = [...required, ...optional];
  const missing = required.filter((key) => !actual.includes(key));
  const unknown = actual.filter((key) => !allowed.includes(key));
  if (missing.length > 0 || unknown.length > 0) {
    const details = [
      missing.length > 0 ? `missing ${missing.join(", ")}` : "",
      unknown.length > 0 ? `unknown ${unknown.join(", ")}` : "",
    ].filter(Boolean).join("; ");
    throw new PresentationContractError(`${label} has invalid fields: ${details}`);
  }
}

function text(value: unknown, label: string, maxLength = 256): string {
  if (
    typeof value !== "string"
    || value.length === 0
    || value.trim() !== value
    || value.length > maxLength
    || [...value].some((character) => character.codePointAt(0)! < 32)
  ) {
    throw new PresentationContractError(`${label} must be supported nonblank trimmed text`);
  }
  return value;
}

function enumValue<T extends string>(value: unknown, allowed: readonly T[], label: string): T {
  if (typeof value !== "string" || !allowed.includes(value as T)) {
    throw new PresentationContractError(`${label} contains an unsupported value`);
  }
  return value as T;
}

function timestamp(value: unknown, label: string): string {
  const parsed = text(value, label);
  if (!RFC3339.test(parsed) || Number.isNaN(Date.parse(parsed))) {
    throw new PresentationContractError(`${label} must be an RFC 3339 timestamp`);
  }
  return parsed;
}

function finiteNumber(
  value: unknown,
  label: string,
  options: { nonnegative?: boolean; positive?: boolean } = {},
): number {
  if (
    typeof value !== "number"
    || !Number.isFinite(value)
    || (options.positive === true && value <= 0)
    || (options.nonnegative === true && value < 0)
  ) {
    throw new PresentationContractError(`${label} must be a valid finite number`);
  }
  return value;
}

function nullableNonnegative(value: unknown, label: string): number | null {
  return value === null ? null : finiteNumber(value, label, { nonnegative: true });
}

function nonnegativeInteger(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) {
    throw new PresentationContractError(`${label} must be a nonnegative integer`);
  }
  return value as number;
}

function sourceIdentity(value: unknown, label: string): string {
  const parsed = text(value, label);
  if (!SOURCE_IDENTITY.test(parsed)) {
    throw new PresentationContractError(`${label} must be an opaque identity, not a path`);
  }
  return parsed;
}

function currency(value: unknown, label: string): string {
  const parsed = text(value, label, 3);
  if (!CURRENCY.test(parsed)) {
    throw new PresentationContractError(`${label} must be a three-letter currency`);
  }
  return parsed;
}

function parseCaptureReference(
  value: unknown,
  expected: {
    name: string;
    path: string;
    producer: string;
    schema: string;
    observedAt: string;
  },
): ArtifactReference | null {
  if (value === null) return null;
  const reference = parseArtifactReference(value, `${expected.name} reference`);
  if (
    reference.name !== expected.name
    || reference.path !== expected.path
    || reference.producer !== expected.producer
    || reference.schema_version !== expected.schema
    || reference.byte_size === null
    || reference.observed_at !== expected.observedAt
    || !SHA256.test(reference.sha256)
  ) {
    throw new PresentationContractError(`${expected.name} reference is inconsistent`);
  }
  return reference;
}

export interface CabinMissionCorrelation {
  mission_id: string;
  request_id: string;
  symbol: string;
  run_mode: RunMode;
}

export function parseCabinContext(
  value: unknown,
  expected?: CabinMissionCorrelation,
): CabinContextV1 {
  const item = objectValue(value, "cabin context");
  exactKeys(item, [
    "schema_version", "mission_id", "request_id", "symbol", "run_mode", "captured_at",
    "market_artifact", "portfolio_artifact", "capture_provenance",
  ], [], "cabin context");
  if (item.schema_version !== CABIN_CONTEXT_SCHEMA) {
    throw new PresentationContractError(`unsupported cabin context schema: ${String(item.schema_version)}`);
  }

  const missionId = text(item.mission_id, "cabin context mission_id", 128);
  const requestId = text(item.request_id, "cabin context request_id", 128);
  if (!MISSION_ID.test(missionId) || !IDENTIFIER.test(requestId)) {
    throw new PresentationContractError("cabin context contains invalid correlation identifiers");
  }
  const symbol = text(item.symbol, "cabin context symbol", 64);
  const runMode = enumValue(item.run_mode, RUN_MODES, "cabin context run_mode");
  const capturedAt = timestamp(item.captured_at, "cabin context captured_at");
  if (
    expected !== undefined
    && (
      missionId !== expected.mission_id
      || requestId !== expected.request_id
      || symbol !== expected.symbol
      || runMode !== expected.run_mode
    )
  ) {
    throw new PresentationContractError("cabin context conflicts with canonical mission correlation");
  }

  const marketArtifact = parseCaptureReference(item.market_artifact, {
    name: "navigator_market",
    path: "presentation/navigator_market.json",
    producer: "navigator",
    schema: NAVIGATOR_MARKET_CONTRACT,
    observedAt: capturedAt,
  });
  const portfolioArtifact = parseCaptureReference(item.portfolio_artifact, {
    name: "portfolio_snapshot",
    path: "presentation/portfolio_snapshot.json",
    producer: "portfolio",
    schema: PORTFOLIO_SNAPSHOT_SCHEMA,
    observedAt: capturedAt,
  });

  const provenance = objectValue(item.capture_provenance, "cabin context capture_provenance");
  exactKeys(provenance, ["market", "portfolio"], [], "cabin context capture_provenance");
  const market = objectValue(provenance.market, "market capture provenance");
  const portfolio = objectValue(provenance.portfolio, "portfolio capture provenance");
  exactKeys(market, ["status", "transport", "source_identity", "navigator_git_revision"], [], "market capture provenance");
  exactKeys(portfolio, ["status", "transport", "source_identity"], [], "portfolio capture provenance");

  const marketStatus = enumValue(market.status, CAPTURE_STATUSES, "market capture status");
  const portfolioStatus = enumValue(portfolio.status, CAPTURE_STATUSES, "portfolio capture status");
  let marketTransport: CaptureTransport | null = null;
  let marketSourceIdentity: string | null = null;
  let navigatorGitRevision: string | null = null;
  if (marketStatus === "CAPTURED") {
    marketTransport = enumValue(market.transport, CAPTURE_TRANSPORTS, "market capture transport");
    marketSourceIdentity = sourceIdentity(market.source_identity, "market source_identity");
    navigatorGitRevision = text(market.navigator_git_revision, "Navigator git revision", 64);
    if (!GIT_REVISION.test(navigatorGitRevision)) {
      throw new PresentationContractError("Navigator git revision must be lowercase hexadecimal");
    }
  } else if (market.transport !== null || market.source_identity !== null || market.navigator_git_revision !== null) {
    throw new PresentationContractError("NOT_CONFIGURED market provenance values must be null");
  }

  let portfolioTransport: CaptureTransport | null = null;
  let portfolioSourceIdentity: string | null = null;
  if (portfolioStatus === "CAPTURED") {
    portfolioTransport = enumValue(portfolio.transport, CAPTURE_TRANSPORTS, "portfolio capture transport");
    if (portfolioTransport !== "LOCAL_JSON") {
      throw new PresentationContractError("portfolio transport must be LOCAL_JSON");
    }
    portfolioSourceIdentity = sourceIdentity(portfolio.source_identity, "portfolio source_identity");
  } else if (portfolio.transport !== null || portfolio.source_identity !== null) {
    throw new PresentationContractError("NOT_CONFIGURED portfolio provenance values must be null");
  }
  if ((marketArtifact === null) !== (marketStatus === "NOT_CONFIGURED")) {
    throw new PresentationContractError("market artifact and capture status disagree");
  }
  if ((portfolioArtifact === null) !== (portfolioStatus === "NOT_CONFIGURED")) {
    throw new PresentationContractError("portfolio artifact and capture status disagree");
  }

  return {
    schema_version: CABIN_CONTEXT_SCHEMA,
    mission_id: missionId,
    request_id: requestId,
    symbol,
    run_mode: runMode,
    captured_at: capturedAt,
    market_artifact: marketArtifact,
    portfolio_artifact: portfolioArtifact,
    capture_provenance: {
      market: {
        status: marketStatus as CaptureStatus,
        transport: marketTransport,
        source_identity: marketSourceIdentity,
        navigator_git_revision: navigatorGitRevision,
      },
      portfolio: {
        status: portfolioStatus as CaptureStatus,
        transport: portfolioTransport,
        source_identity: portfolioSourceIdentity,
      },
    },
  };
}

function parseMarketPoint(value: unknown, index: number): NavigatorMarketPoint {
  const label = `Navigator market points[${index}]`;
  const item = objectValue(value, label);
  exactKeys(item, ["t", "o", "h", "l", "c", "v", "ma", "atr"], [], label);
  return {
    t: nonnegativeInteger(item.t, `${label}.t`),
    o: finiteNumber(item.o, `${label}.o`, { positive: true }),
    h: finiteNumber(item.h, `${label}.h`, { positive: true }),
    l: finiteNumber(item.l, `${label}.l`, { positive: true }),
    c: finiteNumber(item.c, `${label}.c`, { positive: true }),
    v: nonnegativeInteger(item.v, `${label}.v`),
    ma: nullableNonnegative(item.ma, `${label}.ma`),
    atr: nullableNonnegative(item.atr, `${label}.atr`),
  };
}

export function parseNavigatorMarket(value: unknown, expectedSymbol?: string): NavigatorMarket {
  const item = objectValue(value, "Navigator market response");
  exactKeys(item, ["symbol", "name", "category", "timeframe", "ma_period", "currency", "points", "summary"], [], "Navigator market response");
  const symbol = text(item.symbol, "Navigator market symbol", 64);
  if (expectedSymbol !== undefined && symbol !== expectedSymbol) {
    throw new PresentationContractError("Navigator market symbol does not match the mission request");
  }
  const name = text(item.name, "Navigator market name");
  const category = enumValue(item.category, MARKET_CATEGORIES, "Navigator market category");
  const timeframe = enumValue(item.timeframe, TIMEFRAMES, "Navigator market timeframe");
  const maPeriod = typeof item.ma_period === "number" && MA_PERIODS.includes(item.ma_period as typeof MA_PERIODS[number])
    ? item.ma_period as typeof MA_PERIODS[number]
    : null;
  if (maPeriod === null) throw new PresentationContractError("Navigator market ma_period contains an unsupported value");
  const parsedCurrency = currency(item.currency, "Navigator market currency");
  if (!Array.isArray(item.points) || item.points.length === 0) {
    throw new PresentationContractError("Navigator market points must be a nonempty array");
  }
  const points = item.points.map(parseMarketPoint);
  for (let index = 1; index < points.length; index += 1) {
    if (points[index]!.t <= points[index - 1]!.t) {
      throw new PresentationContractError("Navigator market points must be ordered by strictly increasing t");
    }
  }

  const summaryItem = objectValue(item.summary, "Navigator market summary");
  exactKeys(summaryItem, [
    "last_price", "last_ma", "pct_vs_ma", "position", "trend_slope_pct", "volatility",
    "atr", "atr_pct", "ma_period", "bar_count",
  ], [], "Navigator market summary");
  const summary: NavigatorMarketSummary = {
    last_price: finiteNumber(summaryItem.last_price, "Navigator market summary.last_price", { positive: true }),
    last_ma: nullableNonnegative(summaryItem.last_ma, "Navigator market summary.last_ma"),
    pct_vs_ma: finiteNumber(summaryItem.pct_vs_ma, "Navigator market summary.pct_vs_ma"),
    position: enumValue(summaryItem.position, POSITIONS, "Navigator market summary.position"),
    trend_slope_pct: finiteNumber(summaryItem.trend_slope_pct, "Navigator market summary.trend_slope_pct"),
    volatility: enumValue(summaryItem.volatility, VOLATILITY, "Navigator market summary.volatility"),
    atr: finiteNumber(summaryItem.atr, "Navigator market summary.atr", { nonnegative: true }),
    atr_pct: finiteNumber(summaryItem.atr_pct, "Navigator market summary.atr_pct", { nonnegative: true }),
    ma_period: typeof summaryItem.ma_period === "number" && MA_PERIODS.includes(summaryItem.ma_period as typeof MA_PERIODS[number])
      ? summaryItem.ma_period as typeof MA_PERIODS[number]
      : (() => { throw new PresentationContractError("Navigator market summary ma_period is unsupported"); })(),
    bar_count: nonnegativeInteger(summaryItem.bar_count, "Navigator market summary.bar_count"),
  };
  const finalPoint = points.at(-1)!;
  if (
    summary.ma_period !== maPeriod
    || summary.bar_count !== points.length
    || summary.last_price !== finalPoint.c
    || summary.last_ma !== finalPoint.ma
  ) {
    throw new PresentationContractError("Navigator market summary is inconsistent with its points");
  }

  return {
    symbol,
    name,
    category,
    timeframe,
    ma_period: maPeriod,
    currency: parsedCurrency,
    points,
    summary,
  };
}

function parsePortfolioPosition(value: unknown, index: number): PortfolioPosition {
  const label = `portfolio positions[${index}]`;
  const item = objectValue(value, label);
  exactKeys(item, ["symbol"], ["name", "quantity", "market_value", "allocation_percent", "cost_basis", "unrealized_pnl"], label);
  const result: PortfolioPosition = { symbol: text(item.symbol, `${label}.symbol`, 64) };
  if (item.name !== undefined) result.name = text(item.name, `${label}.name`);
  for (const field of ["quantity", "market_value", "cost_basis", "unrealized_pnl"] as const) {
    if (item[field] !== undefined) result[field] = finiteNumber(item[field], `${label}.${field}`);
  }
  if (item.allocation_percent !== undefined) {
    const allocation = finiteNumber(item.allocation_percent, `${label}.allocation_percent`, { nonnegative: true });
    if (allocation > 100) throw new PresentationContractError(`${label}.allocation_percent may not exceed 100`);
    result.allocation_percent = allocation;
  }
  return result;
}

export function parsePortfolioSnapshot(value: unknown): PortfolioSnapshotV1 {
  const item = objectValue(value, "portfolio snapshot");
  exactKeys(
    item,
    ["schema_version", "captured_at", "source_identity", "mode", "account_type", "currency", "positions"],
    ["cash", "equity", "total_exposure"],
    "portfolio snapshot",
  );
  if (item.schema_version !== PORTFOLIO_SNAPSHOT_SCHEMA) {
    throw new PresentationContractError(`unsupported portfolio snapshot schema: ${String(item.schema_version)}`);
  }
  if (!Array.isArray(item.positions)) throw new PresentationContractError("portfolio positions must be an array");
  const positions = item.positions.map(parsePortfolioPosition);
  if (new Set(positions.map((position) => position.symbol)).size !== positions.length) {
    throw new PresentationContractError("portfolio position symbols must be unique");
  }
  const result: PortfolioSnapshotV1 = {
    schema_version: PORTFOLIO_SNAPSHOT_SCHEMA,
    captured_at: timestamp(item.captured_at, "portfolio captured_at"),
    source_identity: sourceIdentity(item.source_identity, "portfolio source_identity"),
    mode: enumValue(item.mode, PORTFOLIO_MODES, "portfolio mode") as PortfolioMode,
    account_type: text(item.account_type, "portfolio account_type", 64),
    currency: currency(item.currency, "portfolio currency"),
    positions,
  };
  for (const field of ["cash", "equity", "total_exposure"] as const) {
    if (item[field] !== undefined) result[field] = finiteNumber(item[field], `portfolio ${field}`, { nonnegative: true });
  }
  return result;
}
