import { loadMissionBundle, type MissionBundle } from "./loadMission";
import { PresentationContractError } from "./validate";

export const CABIN_FEED_SCHEMA = "blackpod.cabin_feed.v1" as const;

interface FeedStatus {
  schema_version: typeof CABIN_FEED_SCHEMA;
  checked_at: string;
  message: string;
}

export interface ReadyLiveMissionFeed extends FeedStatus {
  status: "READY";
  publication_id: string;
  base_url: string;
  observed_at: string;
  mission_id: string;
}

export interface UnavailableLiveMissionFeed extends FeedStatus {
  status: "NOT_CONFIGURED" | "UNAVAILABLE";
}

export type LiveMissionFeed = ReadyLiveMissionFeed | UnavailableLiveMissionFeed;

export interface LiveMissionLoadOptions {
  fetchImpl?: typeof fetch;
  signal?: AbortSignal;
}

function timestamp(value: unknown, label: string): string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$/.test(value)
    || Number.isNaN(Date.parse(value))) {
    throw new PresentationContractError(`${label} must be an ISO UTC timestamp`);
  }
  return value;
}

/** An untrusted pointer may only select an immutable revision on this server. */
export function parseLiveMissionFeed(value: unknown): LiveMissionFeed {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new PresentationContractError("live feed must be an object");
  }
  const item = value as Record<string, unknown>;
  if (item.schema_version !== CABIN_FEED_SCHEMA) throw new PresentationContractError("unsupported live feed schema");
  if (item.status !== "READY" && item.status !== "NOT_CONFIGURED" && item.status !== "UNAVAILABLE") {
    throw new PresentationContractError("unsupported live feed status");
  }
  const keys = ["schema_version", "status", "checked_at", "message",
    ...(item.status === "READY" ? ["publication_id", "base_url", "observed_at", "mission_id"] : [])].sort();
  if (JSON.stringify(Object.keys(item).sort()) !== JSON.stringify(keys)) {
    throw new PresentationContractError("live feed has missing or unknown fields");
  }
  if (typeof item.message !== "string" || item.message.length > 500 || /[\x00-\x1f\x7f]/.test(item.message)) {
    throw new PresentationContractError("live feed message must be bounded plain text");
  }
  const common = {
    schema_version: CABIN_FEED_SCHEMA,
    checked_at: timestamp(item.checked_at, "live feed checked_at"),
    message: item.message,
  };
  if (item.status !== "READY") return { ...common, status: item.status };
  if (typeof item.publication_id !== "string" || !/^[0-9a-f]{64}$/.test(item.publication_id)) {
    throw new PresentationContractError("live feed publication_id must be lowercase SHA-256");
  }
  if (item.base_url !== `revisions/${item.publication_id}/`) {
    throw new PresentationContractError("live feed base_url must select its same-origin immutable publication");
  }
  if (typeof item.mission_id !== "string" || !item.mission_id.trim() || item.mission_id !== item.mission_id.trim()
    || /[\x00-\x1f\x7f]/.test(item.mission_id)) {
    throw new PresentationContractError("live feed mission_id must be nonblank plain text");
  }
  return {
    ...common,
    status: "READY",
    publication_id: item.publication_id,
    base_url: item.base_url,
    observed_at: timestamp(item.observed_at, "live feed observed_at"),
    mission_id: item.mission_id,
  };
}

/** One read; scheduling, timeout ownership, and last-good display stay in the UI. */
export async function loadLiveMissionFeed(options: LiveMissionLoadOptions = {}): Promise<LiveMissionFeed> {
  const transport = options.fetchImpl ?? globalThis.fetch;
  if (typeof transport !== "function") throw new PresentationContractError("fetch is unavailable in this browser");
  let response: Response;
  try {
    response = await transport("/live/current.json", {
      cache: "no-store", headers: { Accept: "application/json" }, signal: options.signal,
    });
  } catch {
    throw new PresentationContractError("live mission feed could not be fetched");
  }
  if (!response.ok) throw new PresentationContractError(`live mission feed returned HTTP ${response.status}`);
  let document: unknown;
  try {
    document = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(await response.arrayBuffer()));
  } catch {
    throw new PresentationContractError("live mission feed is not valid UTF-8 JSON");
  }
  return parseLiveMissionFeed(document);
}

export async function loadLiveMissionBundle(
  feed: LiveMissionFeed,
  options: LiveMissionLoadOptions = {},
): Promise<MissionBundle> {
  // Revalidate even typed callers: no arbitrary URL is delegated to the loader.
  const verified = parseLiveMissionFeed(feed);
  if (verified.status !== "READY") throw new PresentationContractError("live mission publication is not available");
  const bundle = await loadMissionBundle(`/live/${verified.base_url}`, {
    ...options,
    manifestKind: "live",
    expectedManifestSha256: verified.publication_id,
    strictEvidence: true,
  });
  if (bundle.summary.mission_id !== verified.mission_id || bundle.snapshot.observed_at !== verified.observed_at) {
    throw new PresentationContractError("live mission publication conflicts with its feed pointer");
  }
  return bundle;
}
