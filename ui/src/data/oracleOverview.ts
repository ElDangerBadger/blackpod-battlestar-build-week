import type { ArtifactReference, JsonObject } from "../contracts/presentation";
import type { MissionEvidenceName } from "./loadMission";
import { isMissionRelativePath } from "./validate";
import type { MissionViewModel } from "./viewModel";

/** Display meanings of existing canonical measures, never browser-side scores. */
const MEASUREMENTS = [
  ["breadth_score", "Market participation", "Recorded share of measured instruments with positive supplied movement; a 0–1 scale, not market-wide constituent breadth."],
  ["leadership_concentration", "Leadership concentration", "Recorded concentration of absolute movement in the two largest movers; it does not identify which instruments led."],
  ["sector_dispersion", "Dispersion", "Recorded spread between the highest and lowest supplied movement, divided by twice its largest absolute movement."],
  ["rotation_velocity", "Rotation velocity", "Recorded change in relative rankings between comparable observations; unavailable without a usable earlier comparison."],
  ["defensive_strength", "Defensive relative strength", "Recorded average percentile position of the canonical defensive group within the supplied universe; not a return percentage."],
  ["cyclical_strength", "Cyclical relative strength", "Recorded average percentile position of the canonical cyclical group within the supplied universe; not a return percentage."],
  ["risk_on_score", "Risk-on relative strength", "Recorded average percentile position of the canonical risk-on group; not a probability or an instruction to act."],
  ["risk_off_score", "Risk-off relative strength", "Recorded average percentile position of the canonical risk-off group; not a probability or an instruction to act."],
] as const;

export interface OracleMeasurement {
  key: typeof MEASUREMENTS[number][0];
  label: string;
  meaning: string;
  rawValue: number | null;
  value: number | null;
  unavailableReason: string | null;
}
export interface OracleSymbolRow {
  symbol: string;
  price: number | null;
  returnPct: number | null;
  timestamp: string | null;
  coverage: "used" | "excluded" | "missing" | "not-recorded" | "conflicting";
  diagnosticStatus: string | null;
  usedFallback: boolean | null;
  fallbackReason: string | null;
  returnSource: string | null;
  warnings: readonly string[];
  blockers: readonly string[];
}
export interface OracleSymbolGroup {
  id: "sector" | "index" | "excluded" | "other";
  label: string;
  rows: readonly OracleSymbolRow[];
}
export interface OracleOverview {
  status: "AVAILABLE" | "PARTIAL" | "UNAVAILABLE";
  asOf: string | null;
  measurementId: string | null;
  normalizedSnapshotId: string | null;
  diagnosticsId: string | null;
  policy: string | null;
  measurements: readonly OracleMeasurement[];
  groups: readonly OracleSymbolGroup[];
  issues: readonly string[];
  warnings: readonly string[];
  blockers: readonly string[];
  links: readonly { label: string; reference: ArtifactReference }[];
}

const text = (value: unknown): string | null => typeof value === "string" && value.trim().length > 0 ? value : null;
const number = (value: unknown): number | null => typeof value === "number" && Number.isFinite(value) ? value : null;
const object = (value: unknown): JsonObject | null => value !== null && typeof value === "object" && !Array.isArray(value) ? value as JsonObject : null;
const texts = (value: unknown): string[] => Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && Boolean(item.trim())) : [];
const unique = (values: readonly string[]): string[] => [...new Set(values)];
const sameMembers = (a: readonly string[], b: readonly string[]) => a.length === b.length && a.every((item) => b.includes(item));
const REFERENCE_FIELDS = ["name", "path", "sha256", "producer", "byte_size", "schema_version", "observed_at"] as const;

function symbols(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || !item || item.trim() !== item)) return null;
  const result = value as string[];
  return new Set(result).size === result.length ? result : null;
}

function symbolRows(value: unknown): Map<string, JsonObject> | null {
  if (!Array.isArray(value)) return null;
  const result = new Map<string, JsonObject>();
  for (const entry of value) {
    const row = object(entry), symbol = text(row?.symbol);
    if (!row || !symbol || symbol.trim() !== symbol || result.has(symbol)) return null;
    result.set(symbol, row);
  }
  return result;
}

/** Read-only projection of verified mission documents. No fetching, ranking or synthesis. */
export function createOracleOverview(mission: MissionViewModel): OracleOverview {
  const loaded = (name: MissionEvidenceName) => {
    const evidence = mission.evidence.get(name);
    return evidence?.status === "LOADED" ? evidence.document : null;
  };
  const measured = loaded("oracle_measurements"), normalized = loaded("oracle_normalized_snapshot");
  const diagnostics = loaded("oracle_measurement_diagnostics");
  const provenance = object(measured?.provenance);
  const issues: string[] = [];
  const measurementId = text(measured?.measurement_id), normalizedSnapshotId = text(provenance?.normalized_snapshot_id);
  const usableDiagnostics = Boolean(diagnostics && text(diagnostics.diagnostics_id) && normalizedSnapshotId
    && normalizedSnapshotId === text(diagnostics.normalized_snapshot_id) && measurementId
    && measurementId === text(diagnostics.measurement_id)
    && (!text(provenance?.readiness_id) || text(provenance?.readiness_id) === text(diagnostics.readiness_id)));
  const diagnosticRows = usableDiagnostics ? symbolRows(diagnostics?.items) : null;
  const warnings = unique([...texts(measured?.warnings), ...(diagnosticRows ? texts(diagnostics?.warnings) : [])]);
  const blockers = unique([...texts(measured?.blockers), ...(diagnosticRows ? texts(diagnostics?.blockers) : [])]);
  const missingPrior = warnings.includes("MISSING_PRIOR_ORACLE_MEASUREMENTS");
  const measurements: OracleMeasurement[] = MEASUREMENTS.map(([key, label, meaning]) => {
    const rawValue = number(measured?.[key]);
    const unavailableReason = key === "rotation_velocity" && missingPrior
      ? "No usable earlier measurement comparison was recorded. A recorded zero is a placeholder, not evidence of no rotation."
      : rawValue === null ? "No finite value was recorded in the supplied measurement artifact."
        : rawValue < 0 || rawValue > 1 ? "The supplied value is outside the canonical 0–1 range." : null;
    return { key, label, meaning, rawValue, value: unavailableReason ? null : rawValue, unavailableReason };
  });
  let usableSnapshot = Boolean(measured && normalized && normalizedSnapshotId && normalizedSnapshotId === text(normalized?.normalized_snapshot_id));
  if (!measured) issues.push("Oracle measurements are not available in the verified mission evidence.");
  if (!usableSnapshot) issues.push("Per-symbol observations are unavailable: the measurement provenance and normalized snapshot must record the same snapshot ID.");
  for (const key of ["fleet_id", "source_snapshot_id"] as const) {
    const expected = text(provenance?.[key]), supplied = text(normalized?.[key]);
    if (usableSnapshot && expected && supplied && expected !== supplied) {
      issues.push(`Per-symbol observations are unavailable: the recorded ${key} values conflict.`);
      usableSnapshot = false;
    }
  }
  const observed = usableSnapshot ? symbolRows(normalized?.symbols) : null;
  if (usableSnapshot && !observed) issues.push("Per-symbol observations are unavailable: the normalized snapshot has an invalid or duplicate symbol list.");
  if (observed && number(normalized?.symbol_count) !== null && number(normalized?.symbol_count) !== observed.size) {
    issues.push("The recorded normalized symbol count differs from its supplied rows; no missing observations are invented.");
  }

  if (!diagnosticRows) issues.push("Per-symbol diagnostics are unavailable or cannot be correlated to these measurements and this snapshot.");

  const membership = (key: string): string[] | null => {
    if (!provenance || !Object.hasOwn(provenance, key)) return [];
    const result = symbols(provenance[key]);
    if (!result) issues.push(`Per-symbol grouping is unavailable: canonical ${key} membership is malformed or duplicated.`);
    return result;
  };
  const sectors = membership("sector_symbols_expected"), indexes = membership("index_symbols_optional");
  const excluded = membership("symbols_excluded"), missing = membership("symbols_missing");
  const recordedSymbols = measured && Object.hasOwn(measured, "symbols") ? symbols(measured.symbols) : null;
  const used = provenance && Object.hasOwn(provenance, "symbols_used") ? membership("symbols_used") : recordedSymbols;
  let validMembership = Boolean(sectors && indexes && excluded && missing && used && recordedSymbols);
  if (validMembership && !sameMembers(used!, recordedSymbols!)) {
    issues.push("Per-symbol grouping is unavailable: measured symbols conflict with the provenance's used-symbol membership.");
    validMembership = false;
  }
  if (validMembership && (sectors!.some((symbol) => indexes!.includes(symbol))
    || used!.some((symbol) => excluded!.includes(symbol) || missing!.includes(symbol))
    || excluded!.some((symbol) => sectors!.includes(symbol) || indexes!.includes(symbol) || missing!.includes(symbol)))) {
    issues.push("Per-symbol grouping is unavailable: canonical membership lists contain conflicting classifications.");
    validMembership = false;
  }
  if (measured && !validMembership && !issues.some((issue) => issue.startsWith("Per-symbol grouping"))) {
    issues.push("Per-symbol grouping is unavailable: unique canonical measured-symbol membership was not recorded.");
  }

  const returnSources = object(provenance?.return_source_by_symbol);
  const groups: OracleSymbolGroup[] = [];
  if (observed && validMembership) {
    const population = unique([...sectors!, ...indexes!, ...used!, ...excluded!, ...missing!]);
    const unclassified = [...observed.keys()].filter((symbol) => !population.includes(symbol));
    if (unclassified.length) issues.push(`Observed symbols without canonical measurement membership are not classified here: ${unclassified.join(", ")}.`);
    const extraDiagnostics = [...(diagnosticRows?.keys() ?? [])].filter((symbol) => !population.includes(symbol));
    if (extraDiagnostics.length) issues.push(`Diagnostics outside the canonical measurement membership are not joined: ${extraDiagnostics.join(", ")}.`);
    const row = (symbol: string): OracleSymbolRow => {
      const source = observed.get(symbol), diagnostic = diagnosticRows?.get(symbol);
      const expectedCoverage = used!.includes(symbol) ? "used" : excluded!.includes(symbol) ? "excluded" : missing!.includes(symbol) ? "missing" : "not-recorded";
      const flags = ["used", "excluded", "missing"] as const;
      const active = flags.filter((key) => diagnostic?.[key] === true);
      let coverage: OracleSymbolRow["coverage"] = diagnostic ? active.length > 1 ? "conflicting" : active[0] ?? "not-recorded" : expectedCoverage;
      if (diagnostic && expectedCoverage !== "not-recorded" && coverage !== expectedCoverage) coverage = "conflicting";
      if (coverage === "conflicting") issues.push(`${symbol}: canonical diagnostic coverage conflicts with measurement membership; no single coverage claim is made.`);
      if (!source && used!.includes(symbol)) issues.push(`${symbol}: recorded as used, but no matching normalized observation is supplied.`);
      return {
        symbol, price: number(source?.price), returnPct: number(source?.return_pct), timestamp: text(source?.timestamp), coverage,
        diagnosticStatus: text(diagnostic?.status), usedFallback: typeof diagnostic?.used_fallback === "boolean" ? diagnostic.used_fallback : null,
        fallbackReason: text(diagnostic?.fallback_reason), returnSource: text(returnSources?.[symbol]),
        warnings: unique([...texts(source?.warnings), ...texts(diagnostic?.warnings)]), blockers: texts(diagnostic?.blockers),
      };
    };
    const definitions: [OracleSymbolGroup["id"], string, string[]][] = [
      ["sector", "Canonical sector proxies", sectors!], ["index", "Canonical index proxies", indexes!],
      ["excluded", "Observed but excluded from Oracle measurements", excluded!],
      ["other", "Other canonical measurement members", population.filter((symbol) => !sectors!.includes(symbol) && !indexes!.includes(symbol) && !excluded!.includes(symbol))],
    ];
    for (const [id, label, members] of definitions) if (members.length) groups.push({ id, label, rows: members.map(row) });
  }

  const links: OracleOverview["links"][number][] = [];
  for (const [name, label] of [
    ["oracle_measurements", "Oracle measurements and membership"], ["oracle_normalized_snapshot", "Saved normalized observations"],
    ["oracle_measurement_diagnostics", "Oracle coverage and diagnostics"],
  ] as const) {
    const evidence = mission.evidence.get(name), reference = evidence?.reference, indexed = mission.artifactIndex.get(name);
    if (evidence?.status === "LOADED" && reference?.name === name && indexed
      && REFERENCE_FIELDS.every((key) => reference[key] === indexed[key])
      && isMissionRelativePath(reference.path) && !/[%?#\x00-\x1f\x7f]/.test(reference.path)) links.push({ label, reference });
  }
  return {
    status: !measured ? "UNAVAILABLE" : issues.length || measurements.some((item) => item.value === null) ? "PARTIAL" : "AVAILABLE",
    asOf: text(measured?.as_of), measurementId, normalizedSnapshotId,
    diagnosticsId: diagnosticRows ? text(diagnostics?.diagnostics_id) : null,
    policy: text(provenance?.measurement_input_policy), measurements, groups, issues: unique(issues), warnings, blockers, links,
  };
}
