import type {
  ArtifactReference,
  CaptainsLogV1,
  MissionManifest,
  JsonObject,
  MissionSnapshotV1,
  MissionSummaryV2,
} from "../contracts/presentation";
import type {
  CabinContextV1,
  NavigatorMarket,
  PortfolioSnapshotV1,
} from "../contracts/cabinContext";
import {
  PresentationContractError,
  asJsonObject,
  isMissionRelativePath,
  parseCaptainsLog,
  parseDemoManifest,
  parsePresentationManifest,
  parseMissionSnapshot,
  parseMissionSummary,
  validateMissionBundleContracts,
} from "./validate";
import {
  parseCabinContext,
  parseNavigatorMarket,
  parsePortfolioSnapshot,
  type CabinMissionCorrelation,
} from "./validateCabinContext";
import type { NavigatorMarketVariant } from "../contracts/navigatorCatalog";
import { parseNavigatorCatalog } from "./validateNavigatorCatalog";
import { parseNavigatorFleetCatalog } from "./validateNavigatorFleetCatalog";
import type { OracleMarketBrief } from "../contracts/oracleMarketBrief";
import { validateOracleMarketBrief } from "./validateOracleMarketBrief";

/** Known evidence used by the five focused books. Paths are never guessed. */
export const MISSION_EVIDENCE_NAMES = [
  "mission_request",
  "oracle_report",
  "oracle_normalized_snapshot",
  "oracle_measurements",
  "oracle_measurement_diagnostics",
  "oracle_readiness_report",
  "oracle_assessment",
  "oracle_narrative",
  "oracle_modeldock_narrative",
  "oracle_modeldock_provenance",
  "council_synthesis",
  "council_executive_summary",
  "council_candidate_evidence",
  "council_senate_review_evidence",
  "council_senate_deliberation_evidence",
  "council_mandate_policy",
  "council_provenance",
  "governor_rendered_decision",
  "governor_decision_readiness",
  "governor_decision",
  "governor_deliberation",
  "governor_warning_classification",
  "governor_provenance",
  "operator_review_packet",
  "operator_action",
  "operator_receipt",
  "operator_provenance",
  "navigator_handoff_envelope",
  "navigator_staging_receipt",
  "navigator_intake_receipt",
  "navigator_shadow_plan",
  "navigator_provenance",
] as const;

export type MissionEvidenceName = (typeof MISSION_EVIDENCE_NAMES)[number];
export type EvidenceLoadStatus = "LOADED" | "NOT_REFERENCED" | "UNAVAILABLE";

export interface MissionEvidence {
  name: MissionEvidenceName;
  reference: ArtifactReference | null;
  document: JsonObject | null;
  status: EvidenceLoadStatus;
  message: string | null;
}

export interface MissionBundle {
  baseUrl: string;
  summary: MissionSummaryV2;
  captainsLog: CaptainsLogV1;
  manifest: MissionManifest;
  snapshot: MissionSnapshotV1;
  artifactIndex: ReadonlyMap<string, ArtifactReference>;
  evidence: ReadonlyMap<MissionEvidenceName, MissionEvidence>;
  /** Optional, strictly validated Stage 4 presentation supplements. */
  cabinContext: CabinContextV1 | null;
  navigatorMarket: NavigatorMarket | null;
  navigatorVariants?: readonly NavigatorMarketVariant[];
  navigatorFleetVariants?: readonly NavigatorMarketVariant[];
  oracleMarketBrief?: OracleMarketBrief | null;
  portfolio: PortfolioSnapshotV1 | null;
}

export interface CabinPresentationSupplements {
  cabinContext: CabinContextV1 | null;
  navigatorMarket: NavigatorMarket | null;
  portfolio: PortfolioSnapshotV1 | null;
}

export interface LoadMissionBundleOptions {
  fetchImpl?: typeof fetch;
  signal?: AbortSignal;
  /** Legacy replay fixtures retain their original explicit manifest contract. */
  manifestKind?: "demo" | "live";
  /** Live publications are addressed by the digest of their manifest bytes. */
  expectedManifestSha256?: string;
  /** When true, a referenced but unavailable detail artifact rejects loading. */
  strictEvidence?: boolean;
}

/**
 * A primary canonical JSON failure remains fatal. `fallbackMarkdown` may be
 * rendered as read-only text by an error boundary, but must never be parsed
 * into synthetic statuses or Captain's Log entries.
 */
export class MissionBundleLoadError extends PresentationContractError {
  readonly fallbackMarkdown: string | null;

  constructor(message: string, fallbackMarkdown: string | null = null) {
    super(message);
    this.name = "MissionBundleLoadError";
    this.fallbackMarkdown = fallbackMarkdown;
  }
}

interface LoadedJson {
  bytes: Uint8Array;
  document: unknown;
}

/** Bounded parallel I/O; results retain catalog order and never expose a partial catalog. */
async function loadCapturedEntries<T, R>(
  entries: readonly T[], load: (entry: T) => Promise<R>, signal?: AbortSignal,
): Promise<R[]> {
  const results = new Array<R>(entries.length);
  let cursor = 0;
  let failed = false;
  await Promise.all(Array.from({ length: Math.min(4, entries.length) }, async () => {
    while (!failed && cursor < entries.length) {
      if (signal?.aborted) throw new PresentationContractError("Navigator capture loading was cancelled");
      const index = cursor++;
      try {
        results[index] = await load(entries[index]);
      } catch (error) {
        failed = true;
        throw error;
      }
    }
  }));
  if (signal?.aborted) throw new PresentationContractError("Navigator capture loading was cancelled");
  return results;
}

function normalizeBaseUrl(baseUrl: string): string {
  const trimmed = baseUrl.trim();
  if (!trimmed) throw new PresentationContractError("mission data base URL may not be blank");
  return trimmed.endsWith("/") ? trimmed : `${trimmed}/`;
}

export function missionRelativeUrl(baseUrl: string, relativePath: string): string {
  if (!isMissionRelativePath(relativePath)) {
    throw new PresentationContractError("mission asset path must be mission-relative");
  }
  const encoded = relativePath.split("/").map(encodeURIComponent).join("/");
  return `${normalizeBaseUrl(baseUrl)}${encoded}`;
}

function sanitizedLoadMessage(error: unknown): string {
  if (error instanceof PresentationContractError) return error.message;
  return error instanceof Error ? error.message.replace(/[\r\n\t]+/g, " ").slice(0, 240) : "artifact could not be loaded";
}

async function fetchJson(fetchImpl: typeof fetch, url: string, label: string): Promise<LoadedJson> {
  let response: Response;
  try {
    response = await fetchImpl(url, { cache: "no-store", headers: { Accept: "application/json" } });
  } catch {
    throw new PresentationContractError(`${label} could not be fetched`);
  }
  if (!response.ok) {
    throw new PresentationContractError(`${label} returned HTTP ${response.status}`);
  }
  const bytes = new Uint8Array(await response.arrayBuffer());
  let document: unknown;
  try {
    document = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    throw new PresentationContractError(`${label} is not valid UTF-8 JSON`);
  }
  return { bytes, document };
}

async function fetchOptionalJson(
  fetchImpl: typeof fetch,
  url: string,
  label: string,
): Promise<LoadedJson | null> {
  let response: Response;
  try {
    response = await fetchImpl(url, { cache: "no-store", headers: { Accept: "application/json" } });
  } catch {
    throw new PresentationContractError(`${label} could not be fetched`);
  }
  if (response.status === 404) return null;
  if (!response.ok) throw new PresentationContractError(`${label} returned HTTP ${response.status}`);
  const bytes = new Uint8Array(await response.arrayBuffer());
  let document: unknown;
  try {
    document = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    throw new PresentationContractError(`${label} is not valid UTF-8 JSON`);
  }
  return { bytes, document };
}

async function fetchText(fetchImpl: typeof fetch, url: string, label: string): Promise<string> {
  let response: Response;
  try {
    response = await fetchImpl(url, { cache: "no-store" });
  } catch {
    throw new PresentationContractError(`${label} could not be fetched`);
  }
  if (!response.ok) throw new PresentationContractError(`${label} returned HTTP ${response.status}`);
  const text = await response.text();
  if (!text.trim()) throw new PresentationContractError(`${label} is empty`);
  return text;
}

export async function loadCaptainsLogMarkdownFallback(
  baseUrl = "./demo/approved/",
  fetchImpl: typeof fetch = globalThis.fetch,
): Promise<string | null> {
  if (typeof fetchImpl !== "function") return null;
  try {
    return await fetchText(
      fetchImpl,
      missionRelativeUrl(baseUrl, "presentation/captains_log.md"),
      "Captain's Log Markdown fallback",
    );
  } catch {
    return null;
  }
}

async function sha256(bytes: Uint8Array): Promise<string> {
  if (!globalThis.crypto?.subtle) {
    throw new PresentationContractError("SHA-256 verification is unavailable in this browser");
  }
  const source = new Uint8Array(bytes);
  const digest = await globalThis.crypto.subtle.digest("SHA-256", source.buffer);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

/** The optional model report has its own small bound, independent of market history. */
async function fetchBriefJson(fetchImpl: typeof fetch, url: string): Promise<LoadedJson> {
  const response = await fetchImpl(url, { cache: "no-store", redirect: "error", headers: { Accept: "application/json" } });
  const declared = response.headers.get("content-length");
  if (!response.ok || !response.body || (declared !== null && (!/^\d+$/.test(declared) || Number(declared) > 256 * 1024))) {
    await response.body?.cancel().catch(() => {});
    throw new PresentationContractError("Oracle market brief could not be read within its size bound");
  }
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = []; let size = 0;
  try {
    while (true) {
      const result = await reader.read();
      if (result.done) break;
      size += result.value.byteLength;
      if (size > 256 * 1024) throw new PresentationContractError("Oracle market brief exceeds its size bound");
      chunks.push(result.value);
    }
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { return { bytes, document: JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) }; }
  catch { throw new PresentationContractError("Oracle market brief is not valid UTF-8 JSON"); }
}

function briefPointer(document: unknown, pointer: string): unknown {
  if (!pointer.startsWith("/") || /~(?![01])/.test(pointer)) throw new PresentationContractError("Invalid Oracle brief citation");
  let value: unknown = document;
  for (const part of pointer.slice(1).split("/")) {
    const key = part.replaceAll("~1", "/").replaceAll("~0", "~");
    if (Array.isArray(value) && /^(0|[1-9][0-9]*)$/.test(key)) value = value[Number(key)];
    else if (value && typeof value === "object" && Object.hasOwn(value, key)) value = (value as Record<string, unknown>)[key];
    else throw new PresentationContractError("Oracle brief citation is not in supplied evidence");
  }
  return value;
}

async function verifyReference(loaded: LoadedJson, reference: ArtifactReference, label: string): Promise<void> {
  if (reference.byte_size !== null && loaded.bytes.byteLength !== reference.byte_size) {
    throw new PresentationContractError(`${label} byte size does not match its canonical reference`);
  }
  if (await sha256(loaded.bytes) !== reference.sha256) {
    throw new PresentationContractError(`${label} SHA-256 does not match its canonical reference`);
  }
}

/**
 * Load the optional read-only Stage 4 wrapper. A missing wrapper is honest
 * absence. Once it exists, every recorded artifact is mandatory and verified.
 */
export async function loadCabinPresentationSupplements(
  baseUrl: string,
  correlation: CabinMissionCorrelation,
  fetchImpl: typeof fetch = globalThis.fetch,
  expectedContext?: ArtifactReference,
): Promise<CabinPresentationSupplements> {
  if (typeof fetchImpl !== "function") {
    throw new PresentationContractError("fetch is unavailable in this browser");
  }
  const normalizedBase = normalizeBaseUrl(baseUrl);
  const contextLoaded = await (expectedContext ? fetchJson : fetchOptionalJson)(
    fetchImpl,
    missionRelativeUrl(normalizedBase, "presentation/cabin_context.json"),
    "cabin context",
  );
  if (contextLoaded === null) {
    return { cabinContext: null, navigatorMarket: null, portfolio: null };
  }
  if (expectedContext) await verifyReference(contextLoaded, expectedContext, "cabin context");

  const cabinContext = parseCabinContext(contextLoaded.document, correlation);
  if (expectedContext && expectedContext.observed_at !== cabinContext.captured_at) {
    throw new PresentationContractError("cabin context capture time conflicts with its publication reference");
  }
  const [navigatorMarket, portfolio] = await Promise.all([
    cabinContext.market_artifact === null
      ? Promise.resolve(null)
      : fetchJson(
        fetchImpl,
        missionRelativeUrl(normalizedBase, cabinContext.market_artifact.path),
        "Navigator market",
      ).then(async (loaded) => {
        await verifyReference(loaded, cabinContext.market_artifact!, "Navigator market");
        return parseNavigatorMarket(loaded.document, cabinContext.symbol, cabinContext.run_mode);
      }),
    cabinContext.portfolio_artifact === null
      ? Promise.resolve(null)
      : fetchJson(
        fetchImpl,
        missionRelativeUrl(normalizedBase, cabinContext.portfolio_artifact.path),
        "portfolio snapshot",
      ).then(async (loaded) => {
        await verifyReference(loaded, cabinContext.portfolio_artifact!, "portfolio snapshot");
        return parsePortfolioSnapshot(loaded.document);
      }),
  ]);

  if (
    portfolio !== null
    && (
      (cabinContext.run_mode === "LIVE" && portfolio.mode !== "LIVE")
      || (cabinContext.run_mode === "REPLAY" && portfolio.mode !== "FROZEN")
    )
  ) {
    throw new PresentationContractError(
      "portfolio mode must be LIVE for LIVE missions and FROZEN for REPLAY missions",
    );
  }

  return { cabinContext, navigatorMarket, portfolio };
}

async function loadEvidence(
  fetchImpl: typeof fetch,
  baseUrl: string,
  reference: ArtifactReference | undefined,
  name: MissionEvidenceName,
  strict: boolean,
): Promise<MissionEvidence> {
  if (reference === undefined) {
    return {
      name,
      reference: null,
      document: null,
      status: "NOT_REFERENCED",
      message: "Not present in this mission artifact.",
    };
  }
  try {
    const loaded = await fetchJson(fetchImpl, missionRelativeUrl(baseUrl, reference.path), `evidence ${name}`);
    await verifyReference(loaded, reference, `evidence ${name}`);
    return {
      name,
      reference,
      document: asJsonObject(loaded.document, `evidence ${name}`),
      status: "LOADED",
      message: null,
    };
  } catch (error) {
    if (strict) throw error;
    return {
      name,
      reference,
      document: null,
      status: "UNAVAILABLE",
      message: sanitizedLoadMessage(error),
    };
  }
}

/**
 * Load one prepared read-only mission pack. Primary JSON contracts and their
 * recorded hashes are mandatory. Detailed evidence is optional for rendering,
 * but any loaded evidence must match its final-snapshot reference.
 */
export async function loadMissionBundle(
  baseUrl = "./demo/approved/",
  options: LoadMissionBundleOptions = {},
): Promise<MissionBundle> {
  const normalizedBase = normalizeBaseUrl(baseUrl);
  const transport = options.fetchImpl ?? globalThis.fetch;
  if (typeof transport !== "function") {
    throw new PresentationContractError("fetch is unavailable in this browser");
  }
  const fetchImpl: typeof fetch = options.signal
    ? (input, init) => transport(input, { ...init, signal: options.signal })
    : transport;

  const isLive = options.manifestKind === "live";
  if (isLive && !/^[0-9a-f]{64}$/.test(options.expectedManifestSha256 ?? "")) {
    throw new PresentationContractError("live publication requires its manifest SHA-256");
  }

  const manifestLoaded = await fetchJson(
    fetchImpl,
    missionRelativeUrl(normalizedBase, isLive ? "presentation/manifest.json" : "presentation/demo_manifest.json"),
    "presentation manifest",
  );
  if (options.expectedManifestSha256 && await sha256(manifestLoaded.bytes) !== options.expectedManifestSha256) {
    throw new PresentationContractError("manifest SHA-256 does not match its publication ID");
  }
  const manifest = isLive ? parsePresentationManifest(manifestLoaded.document) : parseDemoManifest(manifestLoaded.document);

  const [summaryLoaded, snapshotLoaded] = await Promise.all([
    fetchJson(fetchImpl, missionRelativeUrl(normalizedBase, manifest.mission_summary.path), "mission summary"),
    fetchJson(fetchImpl, missionRelativeUrl(normalizedBase, manifest.final_snapshot.path), "final snapshot"),
  ]);
  let logLoaded: LoadedJson;
  try {
    logLoaded = await fetchJson(
      fetchImpl,
      missionRelativeUrl(normalizedBase, manifest.captains_log.path),
      "Captain's Log",
    );
  } catch (error) {
    const fallbackMarkdown = await loadCaptainsLogMarkdownFallback(normalizedBase, fetchImpl);
    throw new MissionBundleLoadError(
      `${sanitizedLoadMessage(error)}; canonical Captain's Log JSON is required by the presentation manifest`,
      fallbackMarkdown,
    );
  }
  await Promise.all([
    verifyReference(summaryLoaded, manifest.mission_summary, "mission summary"),
    verifyReference(logLoaded, manifest.captains_log, "Captain's Log"),
    verifyReference(snapshotLoaded, manifest.final_snapshot, "final snapshot"),
  ]);

  const summary = parseMissionSummary(summaryLoaded.document);
  const captainsLog = parseCaptainsLog(logLoaded.document);
  const snapshot = parseMissionSnapshot(snapshotLoaded.document);
  validateMissionBundleContracts({ summary, captainsLog, manifest, snapshot });

  if (isLive) {
    // Prove the summary and log derive from the immutable source revision,
    // rather than merely trusting a mutable mission_snapshot.json alias.
    const immutable = await fetchJson(fetchImpl,
      missionRelativeUrl(normalizedBase, summary.generated_from_snapshot.path), "immutable snapshot");
    await Promise.all([
      verifyReference(immutable, summary.generated_from_snapshot, "summary source snapshot"),
      verifyReference(immutable, captainsLog.generated_from_snapshot, "log source snapshot"),
      verifyReference(immutable, manifest.final_snapshot, "immutable final snapshot"),
    ]);
  }

  const expectedContext = "cabin_context" in manifest ? manifest.cabin_context : undefined;
  const supplements = isLive && !expectedContext
    ? { cabinContext: null, navigatorMarket: null, portfolio: null }
    : await loadCabinPresentationSupplements(normalizedBase, {
      mission_id: summary.mission_id,
      request_id: summary.request_id,
      symbol: summary.symbol,
      run_mode: summary.run_mode,
    }, fetchImpl, expectedContext);

  const navigatorVariants: NavigatorMarketVariant[] = [];
  const expectedCatalog = isLive && "navigator_catalog" in manifest ? manifest.navigator_catalog : undefined;
  if (expectedCatalog) {
    if (!supplements.cabinContext || !supplements.navigatorMarket) {
      throw new PresentationContractError("Navigator catalog requires the original captured market context");
    }
    const loadedCatalog = await fetchJson(fetchImpl,
      missionRelativeUrl(normalizedBase, expectedCatalog.path), "Navigator catalog");
    await verifyReference(loadedCatalog, expectedCatalog, "Navigator catalog");
    const catalog = parseNavigatorCatalog(loadedCatalog.document, {
      mission_id: summary.mission_id, request_id: summary.request_id,
      symbol: summary.symbol, run_mode: summary.run_mode,
    }, supplements.navigatorMarket);
    if (catalog.captured_at !== expectedCatalog.observed_at) {
      throw new PresentationContractError("Navigator catalog capture time conflicts with its publication reference");
    }
    navigatorVariants.push(...await loadCapturedEntries(catalog.entries, async (entry) => {
      const loaded = await fetchJson(fetchImpl,
        missionRelativeUrl(normalizedBase, entry.artifact.path), "Navigator market variant");
      await verifyReference(loaded, entry.artifact, "Navigator market variant");
      const market = parseNavigatorMarket(loaded.document, catalog.symbol, catalog.run_mode);
      if (market.timeframe !== entry.timeframe || market.ma_period !== entry.ma_period) {
        throw new PresentationContractError("Navigator market variant timeframe/MA conflicts with its catalog entry");
      }
      return { market, capturedAt: entry.captured_at, sourceIdentity: entry.source_identity,
        navigatorGitRevision: entry.navigator_git_revision, reference: entry.artifact };
    }, options.signal));
  }

  const artifactIndex = new Map(snapshot.artifacts.map((reference) => [reference.name, reference]));
  const evidenceValues = await Promise.all(
    MISSION_EVIDENCE_NAMES.map((name) => loadEvidence(
      fetchImpl,
      normalizedBase,
      artifactIndex.get(name),
      name,
      options.strictEvidence ?? false,
    )),
  );
  const evidence = new Map(evidenceValues.map((entry) => [entry.name, entry]));

  const navigatorFleetVariants: NavigatorMarketVariant[] = [];
  const expectedFleetCatalog = isLive && "navigator_fleet_catalog" in manifest ? manifest.navigator_fleet_catalog : undefined;
  if (expectedFleetCatalog) {
    const fleet = evidence.get("oracle_normalized_snapshot");
    const indexedFleet = artifactIndex.get("oracle_normalized_snapshot");
    if (fleet?.status !== "LOADED" || !fleet.document || !indexedFleet) {
      throw new PresentationContractError("Navigator fleet catalog requires verified canonical normalized fleet evidence");
    }
    const loadedCatalog = await fetchJson(fetchImpl,
      missionRelativeUrl(normalizedBase, expectedFleetCatalog.path), "Navigator fleet catalog");
    await verifyReference(loadedCatalog, expectedFleetCatalog, "Navigator fleet catalog");
    const catalog = parseNavigatorFleetCatalog(loadedCatalog.document, {
      mission_id: summary.mission_id, request_id: summary.request_id,
      symbol: summary.symbol, run_mode: summary.run_mode,
    }, indexedFleet, fleet.document, supplements.navigatorMarket);
    if (catalog.captured_at !== expectedFleetCatalog.observed_at) {
      throw new PresentationContractError("Navigator fleet catalog capture time conflicts with its publication reference");
    }
    navigatorFleetVariants.push(...await loadCapturedEntries(catalog.entries, async (entry) => {
      const loaded = await fetchJson(fetchImpl,
        missionRelativeUrl(normalizedBase, entry.artifact.path), "Navigator fleet market");
      await verifyReference(loaded, entry.artifact, "Navigator fleet market");
      const market = parseNavigatorMarket(loaded.document, entry.symbol, "LIVE");
      if (market.timeframe !== entry.timeframe || market.ma_period !== entry.ma_period) {
        throw new PresentationContractError("Navigator fleet market timeframe/MA conflicts with its catalog entry");
      }
      return { market, capturedAt: entry.captured_at, sourceIdentity: entry.source_identity,
        navigatorGitRevision: catalog.navigator_source.git_revision, reference: entry.artifact,
        navigatorSourceSha256: catalog.navigator_source.backend_sha256, navigatorWorktreeDirty: catalog.navigator_source.worktree_dirty };
    }, options.signal));
  }

  let oracleMarketBrief: OracleMarketBrief | null = null;
  const expectedBrief = isLive && "oracle_market_brief" in manifest ? manifest.oracle_market_brief : undefined;
  if (expectedBrief) {
    const loadedBrief = await fetchBriefJson(fetchImpl, missionRelativeUrl(normalizedBase, expectedBrief.path));
    await verifyReference(loadedBrief, expectedBrief, "Oracle market brief");
    const brief = validateOracleMarketBrief(loadedBrief.document);
    const correlation = brief.evidence;
    if (correlation.mission_id !== summary.mission_id || correlation.request_id !== summary.request_id
      || correlation.symbol !== summary.symbol || correlation.run_mode !== summary.run_mode
      || brief.generated_at !== expectedBrief.observed_at || snapshot.stages.oracle.status !== "SUCCEEDED") {
      throw new PresentationContractError("Oracle market brief conflicts with its mission or publication");
    }
    for (const [name, reference] of Object.entries(correlation.source_artifacts)) {
      const recorded = evidence.get(name as MissionEvidenceName);
      const indexed = artifactIndex.get(name);
      if (recorded?.status !== "LOADED" || !recorded.document || !indexed
        || (["name", "path", "sha256", "producer", "byte_size", "schema_version", "observed_at"] as const)
          .some((key) => indexed[key] !== reference[key])) {
        throw new PresentationContractError("Oracle market brief source differs from verified mission evidence");
      }
    }
    for (const fact of correlation.facts) {
      const actual = briefPointer(evidence.get(fact.source_artifact as MissionEvidenceName)?.document, fact.json_pointer);
      if (JSON.stringify(actual) !== JSON.stringify(fact.value)) {
        throw new PresentationContractError("Oracle market brief fact differs from verified source value");
      }
    }
    if (correlation.as_of !== evidence.get("oracle_measurements")?.document?.as_of) {
      throw new PresentationContractError("Oracle market brief snapshot time conflicts with source evidence");
    }
    oracleMarketBrief = brief;
  }

  return {
    baseUrl: normalizedBase,
    summary,
    captainsLog,
    manifest,
    snapshot,
    artifactIndex,
    evidence,
    ...supplements,
    navigatorVariants,
    navigatorFleetVariants,
    oracleMarketBrief,
  };
}

export function getEvidenceDocument(bundle: MissionBundle, name: MissionEvidenceName): JsonObject | undefined {
  return bundle.evidence.get(name)?.document ?? undefined;
}
