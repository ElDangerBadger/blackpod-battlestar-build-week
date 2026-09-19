import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { JsonObject } from "../contracts/presentation";
import type { MissionEvidenceName } from "../data/loadMission";
import { createMissionViewModel } from "../data/viewModel";
import { artifact, createMissionBundleFixture } from "../test/missionFixture";
import { buildBookDefinitions } from "./bookPages";
import { OracleDiagnostics, OracleOverview } from "./OracleOverview";

function fixture() {
  const bundle = createMissionBundleFixture();
  const documents: Partial<Record<MissionEvidenceName, JsonObject>> = {
    oracle_measurements: {
      measurement_id: "measurement-one", as_of: "2026-09-18T19:05:11Z", symbols: ["XLK", "SPY"],
      breadth_score: 0.5, leadership_concentration: 0.6, sector_dispersion: 0.7,
      rotation_velocity: 0, defensive_strength: 0.3, cyclical_strength: 0.4, risk_on_score: 0.2, risk_off_score: 0.8,
      warnings: ["MISSING_PRIOR_ORACLE_MEASUREMENTS"], blockers: [],
      provenance: { normalized_snapshot_id: "snapshot-one", measurement_input_policy: "canonical-test-policy",
        sector_symbols_expected: ["XLK"], index_symbols_optional: ["SPY"],
        symbols_used: ["XLK", "SPY"], symbols_missing: [], symbols_excluded: ["VXZ"],
        return_source_by_symbol: { XLK: "return_pct", SPY: "price_previous_close_fallback" } },
    },
    oracle_normalized_snapshot: {
      normalized_snapshot_id: "snapshot-one", symbol_count: 3,
      symbols: [{ symbol: "XLK", price: 123.45, return_pct: -1.25, timestamp: "2026-09-18T19:05:11Z" },
        { symbol: "SPY", price: 234.56, return_pct: 0.75, timestamp: "2026-09-18T19:05:11Z" },
        { symbol: "VXZ", price: 45.67, return_pct: 2.5, timestamp: "2026-09-18T19:05:11Z" }],
    },
    oracle_measurement_diagnostics: {
      diagnostics_id: "diagnostics-one", measurement_id: "measurement-one", normalized_snapshot_id: "snapshot-one",
      symbols_used_count: 2, symbols_excluded_count: 1, symbols_missing_count: 0, fallback_count: 1,
      items: [{ symbol: "XLK", used: true, excluded: false, missing: false, status: "OK", used_fallback: false, warnings: [], blockers: [] },
        { symbol: "SPY", used: true, excluded: false, missing: false, status: "WARNING", used_fallback: true,
          fallback_reason: "Recorded price/previous close fallback", warnings: ["SUPPLIED_FALLBACK"], blockers: [] },
        { symbol: "VXZ", used: false, excluded: true, missing: false, status: "EXCLUDED", used_fallback: false, warnings: ["OUTSIDE_MEASUREMENT_POLICY"], blockers: [] }],
    },
  };
  for (const [key, document] of Object.entries(documents)) {
    const name = key as MissionEvidenceName;
    const reference = { ...artifact(name, `oracle/${name}.json`), producer: "oracle" };
    bundle.evidence = new Map(bundle.evidence).set(name, { name, document, reference, status: "LOADED", message: null });
    bundle.artifactIndex = new Map(bundle.artifactIndex).set(name, reference);
  }
  return { bundle, documents };
}

const fetchSpy = vi.fn();
beforeEach(() => { fetchSpy.mockReset(); vi.stubGlobal("fetch", fetchSpy); });
afterEach(() => { expect(fetchSpy).not.toHaveBeenCalled(); vi.unstubAllGlobals(); });

describe("full recorded Oracle overview", () => {
  it("exposes canonical values and grouped observations without opening details or recomputing returns", () => {
    const { bundle, documents } = fixture();
    const before = JSON.stringify(documents);
    render(<OracleOverview viewModel={createMissionViewModel(bundle)} />);
    expect(screen.getByText("0.5")).toBeVisible();
    expect(screen.getByText("0.5").closest("details")).toBeNull();
    const sectors = within(screen.getByRole("table", { name: "Canonical sector proxies" }));
    expect(sectors.getByText("XLK")).toBeVisible();
    expect(sectors.getByText("-1.25%")).toBeVisible();
    expect(sectors.getByText("123.45")).toHaveAttribute("title", "Exact recorded value: 123.45");
    expect(screen.getByRole("table", { name: "Observed but excluded from Oracle measurements" })).toHaveTextContent("VXZ");
    expect(screen.getByText("Excluded from measurements")).toBeVisible();
    expect(JSON.stringify(documents)).toBe(before);
  });

  it("does not present the zero rotation placeholder as measured stability", () => {
    const { bundle } = fixture();
    render(<OracleOverview viewModel={createMissionViewModel(bundle)} />);
    expect(screen.getByText("Unavailable")).toBeVisible();
    expect(screen.getByText(/A recorded zero is a placeholder/)).toBeVisible();
    expect(screen.getByText("0", { selector: "code" })).toBeVisible();
    expect(screen.queryByText("No rotation")).not.toBeInTheDocument();
  });

  it("exposes input status, fallback reasons, and exclusions", () => {
    const { bundle } = fixture();
    render(<OracleDiagnostics viewModel={createMissionViewModel(bundle)} />);
    const table = within(screen.getByRole("table", { name: "Recorded symbol diagnostics" }));
    expect(table.getByText("Recorded price/previous close fallback")).toBeVisible();
    expect(table.getByText("Warning: SUPPLIED_FALLBACK")).toBeVisible();
    expect(table.getByText("Warning: OUTSIDE_MEASUREMENT_POLICY")).toBeVisible();
    expect(table.getByRole("cell", { name: "Excluded from measurements Status: EXCLUDED" })).toBeVisible();
  });

  it("refuses to join observations from another snapshot", () => {
    const { bundle, documents } = fixture();
    documents.oracle_normalized_snapshot!.normalized_snapshot_id = "another-snapshot";
    render(<OracleOverview viewModel={createMissionViewModel(bundle)} />);
    expect(screen.getByText(/must record the same snapshot ID/)).toBeVisible();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText("0.5")).toBeVisible();
  });

  it("keeps the six-page book and original source links while exposing pages two and three", () => {
    const { bundle } = fixture();
    const oracle = buildBookDefinitions(createMissionViewModel(bundle)).find((book) => book.id === "oracle")!;
    expect(oracle.pages).toHaveLength(6);
    render(<>{oracle.pages[1].content}{oracle.pages[2].content}</>);
    expect(screen.getByRole("region", { name: "Oracle measurements and market coverage" }).closest("details")).toBeNull();
    expect(screen.getByRole("region", { name: "Oracle per-symbol diagnostics" }).closest("details")).toBeNull();
    expect(oracle.pages[1].evidencePaths).toContain("oracle/oracle_normalized_snapshot.json");
    expect(oracle.pages[2].evidencePaths).toContain("oracle/oracle_measurement_diagnostics.json");
  });

  it("keeps missing and unaligned evidence explicit, with no substitute prices", () => {
    const bundle = createMissionBundleFixture();
    bundle.evidence = new Map();
    render(<OracleOverview viewModel={createMissionViewModel(bundle)} />);
    expect(screen.getByText(/Oracle measurements are not available/)).toBeVisible();
    expect(screen.getAllByText("Unavailable")).toHaveLength(8);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
