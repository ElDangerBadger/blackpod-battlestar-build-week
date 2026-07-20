import type {
  ArtifactReference,
  CaptainsLogV1,
  DemoManifestV1,
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

/** Known evidence used by the five focused books. Paths are never guessed. */
export const MISSION_EVIDENCE_NAMES = [
  "mission_request",
  "oracle_report",
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
  manifest: DemoManifestV1;
  snapshot: MissionSnapshotV1;
  artifactIndex: ReadonlyMap<string, ArtifactReference>;
  evidence: ReadonlyMap<MissionEvidenceName, MissionEvidence>;
  /** Optional, strictly validated Stage 4 presentation supplements. */
  cabinContext: CabinContextV1 | null;
  navigatorMarket: NavigatorMarket | null;
  portfolio: PortfolioSnapshotV1 | null;
}

export interface CabinPresentationSupplements {
  cabinContext: CabinContextV1 | null;
  navigatorMarket: NavigatorMarket | null;
  portfolio: PortfolioSnapshotV1 | null;
}

export interface LoadMissionBundleOptions {
  fetchImpl?: typeof fetch;
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
): Promise<CabinPresentationSupplements> {
  if (typeof fetchImpl !== "function") {
    throw new PresentationContractError("fetch is unavailable in this browser");
  }
  const normalizedBase = normalizeBaseUrl(baseUrl);
  const contextLoaded = await fetchOptionalJson(
    fetchImpl,
    missionRelativeUrl(normalizedBase, "presentation/cabin_context.json"),
    "cabin context",
  );
  if (contextLoaded === null) {
    return { cabinContext: null, navigatorMarket: null, portfolio: null };
  }

  const cabinContext = parseCabinContext(contextLoaded.document, correlation);
  const [navigatorMarket, portfolio] = await Promise.all([
    cabinContext.market_artifact === null
      ? Promise.resolve(null)
      : fetchJson(
        fetchImpl,
        missionRelativeUrl(normalizedBase, cabinContext.market_artifact.path),
        "Navigator market",
      ).then(async (loaded) => {
        await verifyReference(loaded, cabinContext.market_artifact!, "Navigator market");
        return parseNavigatorMarket(loaded.document, cabinContext.symbol);
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
  const fetchImpl = options.fetchImpl ?? globalThis.fetch;
  if (typeof fetchImpl !== "function") {
    throw new PresentationContractError("fetch is unavailable in this browser");
  }

  const manifestLoaded = await fetchJson(
    fetchImpl,
    missionRelativeUrl(normalizedBase, "presentation/demo_manifest.json"),
    "demo manifest",
  );
  const manifest = parseDemoManifest(manifestLoaded.document);

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
      `${sanitizedLoadMessage(error)}; canonical Captain's Log JSON is required by the demo manifest`,
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

  const supplements = await loadCabinPresentationSupplements(normalizedBase, {
    mission_id: summary.mission_id,
    request_id: summary.request_id,
    symbol: summary.symbol,
    run_mode: summary.run_mode,
  }, fetchImpl);

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

  return {
    baseUrl: normalizedBase,
    summary,
    captainsLog,
    manifest,
    snapshot,
    artifactIndex,
    evidence,
    ...supplements,
  };
}

export function getEvidenceDocument(bundle: MissionBundle, name: MissionEvidenceName): JsonObject | undefined {
  return bundle.evidence.get(name)?.document ?? undefined;
}
