import { describe, expect, it } from "vitest";
import type { JsonObject } from "../contracts/presentation";
import { artifact, createMissionBundleFixture } from "../test/missionFixture";
import type { MissionEvidenceName } from "./loadMission";
import { createOracleOverview } from "./oracleOverview";
import { createMissionViewModel } from "./viewModel";

function fixture() {
  const bundle = createMissionBundleFixture();
  bundle.summary.important_warnings = [];
  const measured: JsonObject = {
    measurement_id: "measurement-1", as_of: "2026-09-18T19:05:11Z", symbols: ["SECTOR", "INDEX"],
    breadth_score: .5, leadership_concentration: 1, sector_dispersion: .75, rotation_velocity: .2,
    defensive_strength: .25, cyclical_strength: .75, risk_on_score: .6, risk_off_score: .4, warnings: [], blockers: [],
    provenance: {
      normalized_snapshot_id: "snapshot-1", source_snapshot_id: "raw-1", fleet_id: "fleet-1", readiness_id: "readiness-1",
      measurement_input_policy: "canonical-policy-v1", sector_symbols_expected: ["SECTOR"], index_symbols_optional: ["INDEX"],
      symbols_used: ["SECTOR", "INDEX"], symbols_excluded: ["OUTSIDE"], symbols_missing: [],
      return_source_by_symbol: { SECTOR: "return_pct", INDEX: "gap_pct" },
    },
  };
  const normalized: JsonObject = {
    normalized_snapshot_id: "snapshot-1", source_snapshot_id: "raw-1", fleet_id: "fleet-1", symbol_count: 3,
    symbols: [
      { symbol: "OUTSIDE", price: 50, return_pct: 4, timestamp: "2026-09-18T19:05:10Z", warnings: [] },
      { symbol: "INDEX", price: 200, return_pct: null, gap_pct: -.2, timestamp: "2026-09-18T19:05:09Z", warnings: ["Recorded row warning"] },
      { symbol: "SECTOR", price: 100, return_pct: 1.25, timestamp: "2026-09-18T19:05:08Z", warnings: [] },
    ],
  };
  const diagnostics: JsonObject = {
    diagnostics_id: "diagnostics-1", normalized_snapshot_id: "snapshot-1", measurement_id: "measurement-1", readiness_id: "readiness-1",
    items: [
      { symbol: "SECTOR", used: true, excluded: false, missing: false, status: "OK", used_fallback: false, fallback_reason: "", warnings: [], blockers: [] },
      { symbol: "INDEX", used: true, excluded: false, missing: false, status: "WARNING", used_fallback: true, fallback_reason: "Recorded gap fallback", warnings: ["Recorded diagnostic warning"], blockers: [] },
      { symbol: "OUTSIDE", used: false, excluded: true, missing: false, status: "EXCLUDED", used_fallback: false, fallback_reason: "", warnings: [], blockers: [] },
    ], warnings: [], blockers: [],
  };
  const documents: Partial<Record<MissionEvidenceName, JsonObject>> = {
    oracle_measurements: measured, oracle_normalized_snapshot: normalized, oracle_measurement_diagnostics: diagnostics,
  };
  const evidence = new Map(bundle.evidence), index = new Map(bundle.artifactIndex);
  for (const [name, document] of Object.entries(documents)) {
    const reference = artifact(name, `oracle/${name}.json`);
    evidence.set(name as MissionEvidenceName, { name: name as MissionEvidenceName, reference, document, status: "LOADED", message: null });
    index.set(name, reference);
  }
  bundle.evidence = evidence;
  bundle.artifactIndex = index;
  return { bundle, evidence, index, measured, provenance: measured.provenance as JsonObject, normalized, diagnostics,
    view: () => createOracleOverview(createMissionViewModel(bundle)) };
}

describe("canonical Oracle overview projection", () => {
  it("exposes eight unmodified raw measurements with meanings and canonical membership, without ranking", () => {
    const test = fixture(), before = JSON.stringify([test.measured, test.normalized, test.diagnostics]);
    const overview = test.view();
    expect(overview.status).toBe("AVAILABLE");
    expect(overview.measurements).toHaveLength(8);
    expect(overview.measurements.map((item) => item.rawValue)).toEqual([.5, 1, .75, .2, .25, .75, .6, .4]);
    expect(overview.measurements.every((item) => item.meaning && item.value === item.rawValue)).toBe(true);
    expect(overview).toMatchObject({ asOf: "2026-09-18T19:05:11Z", measurementId: "measurement-1", normalizedSnapshotId: "snapshot-1", diagnosticsId: "diagnostics-1", policy: "canonical-policy-v1" });
    expect(overview.groups.map((group) => [group.id, group.rows.map((row) => row.symbol)])).toEqual([
      ["sector", ["SECTOR"]], ["index", ["INDEX"]], ["excluded", ["OUTSIDE"]],
    ]);
    expect(overview.groups[0].rows[0]).toMatchObject({ price: 100, returnPct: 1.25, timestamp: "2026-09-18T19:05:08Z", coverage: "used", returnSource: "return_pct" });
    expect(overview.groups[0].rows[0]).not.toHaveProperty("rank");
    expect(overview.links).toHaveLength(3);
    expect(JSON.stringify([test.measured, test.normalized, test.diagnostics])).toBe(before);
  });

  it("preserves fallback and excluded evidence without substituting gap_pct for missing return_pct", () => {
    const overview = fixture().view(), row = overview.groups[1].rows[0];
    expect(row).toMatchObject({ returnPct: null, diagnosticStatus: "WARNING", usedFallback: true, fallbackReason: "Recorded gap fallback", returnSource: "gap_pct" });
    expect(row.warnings).toEqual(["Recorded row warning", "Recorded diagnostic warning"]);
    expect(overview.groups[2].rows[0]).toMatchObject({ coverage: "excluded", price: 50, returnPct: 4 });
  });

  it.each(["measurement", "diagnostics"])("marks missing-prior rotation unavailable from %s warnings but preserves its raw placeholder", (source) => {
    const test = fixture();
    test.measured.rotation_velocity = 0;
    if (source === "measurement") test.measured.warnings = ["MISSING_PRIOR_ORACLE_MEASUREMENTS"];
    if (source === "diagnostics") test.diagnostics.warnings = ["MISSING_PRIOR_ORACLE_MEASUREMENTS"];
    expect(test.view().measurements.find((item) => item.key === "rotation_velocity")).toMatchObject({ rawValue: 0, value: null, unavailableReason: expect.stringContaining("not evidence of no rotation") });
    expect(test.view().status).toBe("PARTIAL");
  });

  it("keeps a recorded zero available when no missing-prior warning applies", () => {
    const test = fixture(); test.measured.rotation_velocity = 0;
    expect(test.view().measurements.find((item) => item.key === "rotation_velocity")).toMatchObject({ rawValue: 0, value: 0, unavailableReason: null });
  });

  it("does not let uncorrelated diagnostic warnings or global mission warnings reinterpret a measurement", () => {
    const test = fixture(); test.measured.rotation_velocity = .2;
    test.bundle.summary.important_warnings = ["MISSING_PRIOR_ORACLE_MEASUREMENTS"];
    test.diagnostics.measurement_id = "different";
    test.diagnostics.warnings = ["MISSING_PRIOR_ORACLE_MEASUREMENTS"];
    test.diagnostics.blockers = ["STALE_OTHER_MEASUREMENT"];
    expect(test.view().measurements.find((item) => item.key === "rotation_velocity")).toMatchObject({ value: .2, unavailableReason: null });
    expect(test.view().warnings).toEqual([]);
    expect(test.view().blockers).toEqual([]);
  });

  it.each([null, "0.7", false, Infinity, NaN, -1, 2])("does not coerce, clamp or normalize invalid measurement %s", (value) => {
    const test = fixture(); test.measured.breadth_score = value;
    expect(test.view().measurements[0].value).toBeNull();
    expect(test.view().measurements[0].unavailableReason).not.toBeNull();
    if (value === -1 || value === 2) expect(test.view().measurements[0].rawValue).toBe(value);
  });

  it.each(["missing-provenance-id", "different-snapshot", "different-fleet", "different-source"])("does not join symbol data across %s", (mismatch) => {
    const test = fixture();
    if (mismatch === "missing-provenance-id") delete test.provenance.normalized_snapshot_id;
    if (mismatch === "different-snapshot") test.normalized.normalized_snapshot_id = "different";
    if (mismatch === "different-fleet") test.normalized.fleet_id = "different";
    if (mismatch === "different-source") test.normalized.source_snapshot_id = "different";
    expect(test.view().groups).toEqual([]);
    expect(test.view().issues.join(" ")).toMatch(/Per-symbol observations are unavailable/);
    expect(test.view().measurements[0].value).toBe(.5);
  });

  it.each(["normalized_snapshot_id", "measurement_id", "readiness_id"])("does not attach diagnostic records with conflicting %s", (key) => {
    const test = fixture(); test.diagnostics[key] = "different";
    const overview = test.view();
    expect(overview.groups[0].rows[0]).toMatchObject({ price: 100, coverage: "used", diagnosticStatus: null, usedFallback: null, fallbackReason: null });
    expect(overview.diagnosticsId).toBeNull();
    expect(overview.issues.join(" ")).toMatch(/diagnostics are unavailable or cannot be correlated/);
  });

  it.each(["normalized_snapshot_id", "measurement_id", "readiness_id", "diagnostics_id"])("does not attach incomplete diagnostic records without %s", (key) => {
    const test = fixture(); delete test.diagnostics[key];
    expect(test.view().groups[0].rows[0].diagnosticStatus).toBeNull();
    expect(test.view().diagnosticsId).toBeNull();
    expect(test.view().issues.join(" ")).toMatch(/diagnostics are unavailable or cannot be correlated/);
  });

  it("will not display cached documents whose evidence is unavailable", () => {
    const test = fixture();
    test.evidence.set("oracle_measurements", { ...test.evidence.get("oracle_measurements")!, status: "UNAVAILABLE" });
    const overview = test.view();
    expect(overview.status).toBe("UNAVAILABLE");
    expect(overview.groups).toEqual([]);
    expect(overview.measurements.every((item) => item.value === null)).toBe(true);
    expect(overview.links.some((item) => item.reference.name === "oracle_measurements")).toBe(false);
  });

  it("does not deduplicate duplicate normalized symbols or duplicate diagnostics silently", () => {
    const test = fixture();
    (test.normalized.symbols as JsonObject[]).push({ symbol: "SECTOR" });
    expect(test.view().groups).toEqual([]);
    expect(test.view().issues.join(" ")).toMatch(/invalid or duplicate symbol list/);
    const other = fixture(); (other.diagnostics.items as JsonObject[]).push({ symbol: "SECTOR" });
    expect(other.view().groups[0].rows[0].diagnosticStatus).toBeNull();
    expect(other.view().issues.join(" ")).toMatch(/diagnostics are unavailable/);
  });

  it.each(["duplicate", "group-overlap", "used-excluded", "used-list-mismatch", "invalid-membership"])("fails grouping explicitly for %s", (kind) => {
    const test = fixture();
    if (kind === "duplicate") test.provenance.sector_symbols_expected = ["SECTOR", "SECTOR"];
    if (kind === "group-overlap") test.provenance.index_symbols_optional = ["SECTOR"];
    if (kind === "used-excluded") test.provenance.symbols_excluded = ["SECTOR", "OUTSIDE"];
    if (kind === "used-list-mismatch") test.provenance.symbols_used = ["INDEX"];
    if (kind === "invalid-membership") test.provenance.symbols_excluded = "OUTSIDE";
    expect(test.view().groups).toEqual([]);
    expect(test.view().issues.join(" ")).toMatch(/Per-symbol grouping is unavailable/);
  });

  it("does not guess sector/index membership from symbols and leaves uncovered observed rows unclassified", () => {
    const test = fixture(); delete test.provenance.sector_symbols_expected; delete test.provenance.index_symbols_optional;
    (test.normalized.symbols as JsonObject[]).push({ symbol: "AAPL", price: 300, return_pct: 3 });
    test.normalized.symbol_count = 4;
    expect(test.view().groups.map((group) => group.id)).toEqual(["excluded", "other"]);
    expect(test.view().groups.flatMap((group) => group.rows).some((row) => row.symbol === "AAPL")).toBe(false);
    expect(test.view().issues.join(" ")).toMatch(/without canonical measurement membership.*AAPL/);
  });

  it("exposes conflicting diagnostic coverage rather than resolving it in the browser", () => {
    const test = fixture(); (test.diagnostics.items as JsonObject[])[0].excluded = true;
    expect(test.view().groups[0].rows[0].coverage).toBe("conflicting");
    expect(test.view().issues.join(" ")).toMatch(/SECTOR: canonical diagnostic coverage conflicts/);
  });

  it("does not invent prices, zero returns or timestamps for missing canonical members", () => {
    const test = fixture();
    test.provenance.sector_symbols_expected = ["SECTOR", "ABSENT"];
    test.provenance.symbols_missing = ["ABSENT"];
    expect(test.view().groups[0].rows[1]).toMatchObject({ symbol: "ABSENT", coverage: "missing", price: null, returnPct: null, timestamp: null });
    const row = (test.normalized.symbols as JsonObject[])[2]; row.price = "100"; row.return_pct = false;
    expect(test.view().groups[0].rows[0]).toMatchObject({ price: null, returnPct: null });
  });

  it("records missing used observations and mismatched counts instead of manufacturing rows", () => {
    const test = fixture(); test.normalized.symbols = (test.normalized.symbols as JsonObject[]).filter((row) => row.symbol !== "SECTOR");
    expect(test.view().groups[0].rows[0]).toMatchObject({ price: null, returnPct: null });
    expect(test.view().issues.join(" ")).toMatch(/symbol count differs/);
    expect(test.view().issues.join(" ")).toMatch(/recorded as used, but no matching normalized observation/);
  });

  it.each(["../secret.json", "oracle/%2e%2e/file.json", "https://example.invalid/source", "oracle/source.json?secret", "oracle\\source.json"])("does not link unsafe path %s", (path) => {
    const test = fixture(), reference = { ...test.index.get("oracle_measurements")!, path };
    test.index.set("oracle_measurements", reference);
    test.evidence.set("oracle_measurements", { ...test.evidence.get("oracle_measurements")!, reference });
    expect(test.view().links.some((item) => item.reference.name === "oracle_measurements")).toBe(false);
  });

  it.each(["name", "sha256", "path", "observed_at", "producer"])("does not link references that differ from the loaded index in %s", (key) => {
    const test = fixture(); test.index.set("oracle_measurements", { ...test.index.get("oracle_measurements")!, [key]: "different" });
    expect(test.view().links.some((item) => item.reference.name === "oracle_measurements")).toBe(false);
  });

  it("returns explicit absence with no inferred population when no Oracle evidence exists", () => {
    const overview = createOracleOverview(createMissionViewModel(createMissionBundleFixture()));
    expect(overview).toMatchObject({ status: "UNAVAILABLE", groups: [], links: [], asOf: null, policy: null });
    expect(overview.measurements.every((item) => item.value === null)).toBe(true);
  });
});
