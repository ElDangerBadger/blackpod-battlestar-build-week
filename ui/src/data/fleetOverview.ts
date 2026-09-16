import type { ArtifactReference, JsonObject } from "../contracts/presentation";
import type { MissionEvidenceName } from "./loadMission";
import { isMissionRelativePath } from "./validate";
import type { MissionViewModel } from "./viewModel";

export type OracleCoverage = "used" | "excluded" | "missing" | "not-recorded" | "conflicting";
export interface RecordedFleetRow {
  symbol: string;
  price: number | null;
  returnPct: number | null;
  timestamp: string | null;
  coverage: OracleCoverage;
  candidateState: string | null;
  candidateReasons: readonly string[];
}
export interface RecordedFleetOverview {
  source: "normalized" | "fallback" | "none";
  fleetId: string | null;
  observedAt: string | null;
  rows: readonly RecordedFleetRow[];
  notes: readonly string[];
  links: readonly { label: string; reference: ArtifactReference }[];
}

const text = (value: unknown): string | null => typeof value === "string" && value.trim().length > 0 ? value : null;
const numeric = (value: unknown): number | null => typeof value === "number" && Number.isFinite(value) ? value : null;
const object = (value: unknown): JsonObject | null => value !== null && typeof value === "object" && !Array.isArray(value) ? value as JsonObject : null;
const stringList = (value: unknown): readonly string[] => Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === "string") : [];

function rows(value: unknown): JsonObject[] | null {
  if (!Array.isArray(value)) return null;
  const result: JsonObject[] = [];
  const seen = new Set<string>();
  for (const item of value) {
    const record = object(item);
    const symbol = text(record?.symbol);
    if (!record || !symbol || symbol.trim() !== symbol || seen.has(symbol)) return null;
    seen.add(symbol);
    result.push(record);
  }
  return result;
}

function loaded(mission: MissionViewModel, name: MissionEvidenceName): JsonObject | null {
  const evidence = mission.evidence.get(name);
  return evidence?.status === "LOADED" ? evidence.document : null;
}

function coverage(record: JsonObject | undefined): OracleCoverage {
  if (!record) return "not-recorded";
  const flags = [record.used === true, record.excluded === true, record.missing === true];
  if (flags.filter(Boolean).length > 1) return "conflicting";
  if (flags[0]) return "used";
  if (flags[1]) return "excluded";
  if (flags[2]) return "missing";
  return "not-recorded";
}

/** Read-only joins of verified saved evidence. No registry, prices or membership are invented. */
export function createRecordedFleetOverview(mission: MissionViewModel): RecordedFleetOverview {
  const normalized = loaded(mission, "oracle_normalized_snapshot");
  const diagnostics = loaded(mission, "oracle_measurement_diagnostics");
  const candidates = loaded(mission, "council_candidate_evidence");
  const observed = normalized ? rows(normalized.symbols) : null;
  const diagnosticRows = diagnostics ? rows(diagnostics.items) : null;
  const candidateRows = candidates ? rows(candidates.candidates) : null;
  const notes: string[] = [];
  if (normalized && observed === null) notes.push("The normalized snapshot has no usable unique symbol list; coverage records are shown instead.");
  if (diagnostics && diagnosticRows === null) notes.push("The diagnostic symbol list is unavailable or ambiguous; no per-symbol coverage is inferred.");
  if (candidates && candidateRows === null) notes.push("The candidate symbol list is unavailable or ambiguous; no candidate classifications are inferred.");
  const fallbackAnchor = diagnosticRows && diagnosticRows.length > 0 ? diagnostics : candidates;
  const anchorId = observed !== null ? text(normalized?.normalized_snapshot_id) : text(fallbackAnchor?.normalized_snapshot_id);
  const aligned = (document: JsonObject | null, label: string) => {
    if (!document) return false;
    // A fallback may show its own fields without claiming a join to another source.
    if (observed === null && document === fallbackAnchor) return true;
    const documentId = text(document.normalized_snapshot_id);
    if (!anchorId || !documentId || anchorId !== documentId) {
      notes.push(`${label} cannot be joined: a matching normalized snapshot ID is not recorded.`);
      return false;
    }
    return true;
  };
  const usableDiagnostics = diagnosticRows && aligned(diagnostics, "Oracle diagnostics") ? diagnosticRows : [];
  const usableCandidates = candidateRows && aligned(candidates, "Candidate records") ? candidateRows : [];
  const diagnosticIndex = new Map(usableDiagnostics.map((item) => [item.symbol as string, item]));
  const candidateIndex = new Map(usableCandidates.map((item) => [item.symbol as string, item]));
  const fallback = [...new Set([...usableDiagnostics, ...usableCandidates].map((item) => item.symbol as string))];
  const selected: JsonObject[] = observed ?? fallback.map((symbol) => ({ symbol }));
  if (observed !== null && numeric(normalized?.symbol_count) !== null && normalized?.symbol_count !== observed.length) {
    notes.push("The recorded symbol count differs from the listed rows; this table shows the supplied rows without inventing missing symbols.");
  }
  const links: { label: string; reference: ArtifactReference }[] = [];
  const configured = mission.artifactIndex.get("oracle_fleet_input");
  if (configured?.name === "oracle_fleet_input" && isMissionRelativePath(configured.path)) links.push({ label: "Configured fleet input (original file)", reference: configured });
  const evidenceLinks: readonly [MissionEvidenceName, string][] = [
    ["oracle_normalized_snapshot", "Observed fleet snapshot"],
    ["oracle_measurement_diagnostics", "Oracle coverage diagnostics"],
    ["council_candidate_evidence", "Council candidate record"],
  ];
  for (const [name, label] of evidenceLinks) {
    const evidence = mission.evidence.get(name);
    if (evidence?.status === "LOADED" && evidence.reference?.name === name && isMissionRelativePath(evidence.reference.path)) links.push({ label, reference: evidence.reference });
  }
  return {
    source: observed !== null ? "normalized" : selected.length ? "fallback" : "none",
    fleetId: observed !== null ? text(normalized?.fleet_id) : usableCandidates.length ? text(candidates?.fleet_id) : null,
    observedAt: observed !== null ? text(normalized?.as_of) ?? text(normalized?.generated_at) : null,
    rows: selected.map((item) => {
      const symbol = item.symbol as string;
      const candidate = candidateIndex.get(symbol);
      return {
        symbol,
        price: observed !== null ? numeric(item.price) : null,
        returnPct: observed !== null ? numeric(item.return_pct) : null,
        timestamp: observed !== null ? text(item.timestamp) : null,
        coverage: coverage(diagnosticIndex.get(symbol)),
        candidateState: text(candidate?.candidate_state),
        candidateReasons: stringList(candidate?.reasons),
      };
    }),
    notes,
    links,
  };
}

export const ORACLE_COVERAGE_LABELS: Readonly<Record<OracleCoverage, string>> = {
  used: "Used by Oracle", excluded: "Excluded from Oracle", missing: "Missing for Oracle",
  "not-recorded": "Coverage not recorded", conflicting: "Conflicting coverage flags",
};
