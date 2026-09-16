import { describe, expect, it } from "vitest";
import type { JsonObject } from "../contracts/presentation";
import { artifact, createMissionBundleFixture } from "../test/missionFixture";
import { createRecordedFleetOverview } from "./fleetOverview";
import type { MissionEvidenceName } from "./loadMission";
import { createMissionViewModel } from "./viewModel";

function fixture() {
  const bundle = createMissionBundleFixture();
  const evidence = new Map(bundle.evidence);
  const documents: Partial<Record<MissionEvidenceName, JsonObject>> = {
    oracle_normalized_snapshot: { normalized_snapshot_id: "snapshot-one", fleet_id: "fleet-recorded", as_of: "2026-09-15T23:05:20Z", symbol_count: 3,
      symbols: [{ symbol: "XLK", price: 183.74, return_pct: -0.468026, timestamp: "2026-09-15T23:05:20Z" }, { symbol: "VXZ", price: 51, return_pct: 2 }, { symbol: "MTUM" }] },
    oracle_measurement_diagnostics: { normalized_snapshot_id: "snapshot-one", items: [{ symbol: "XLK", used: true, excluded: false, missing: false }, { symbol: "VXZ", used: false, excluded: true, missing: false }, { symbol: "MTUM", used: false, excluded: true, missing: false }] },
    council_candidate_evidence: { normalized_snapshot_id: "snapshot-one", fleet_id: "fleet-recorded", candidates: [{ symbol: "XLK", candidate_state: "OBSERVE", reasons: ["Recorded reason"] }, { symbol: "MTUM", candidate_state: "WATCH" }, { symbol: "AAPL", candidate_state: "REVIEW" }] },
  };
  for (const [name, document] of Object.entries(documents)) {
    const reference = artifact(name, `oracle/${name}.json`);
    evidence.set(name as MissionEvidenceName, { name: name as MissionEvidenceName, reference, document, status: "LOADED", message: null });
  }
  bundle.evidence = evidence;
  const configured = artifact("oracle_fleet_input", "oracle/inputs/oracles_vapors.example.yaml");
  bundle.artifactIndex = new Map([[configured.name, configured]]);
  return { bundle, evidence, documents, view: () => createMissionViewModel(bundle) };
}

describe("recorded fleet overview", () => {
  it("keeps every observed symbol in source order and joins only matching snapshot records", () => {
    const test = fixture();
    const before = JSON.stringify(test.documents);
    const fleet = createRecordedFleetOverview(test.view());
    expect(fleet.source).toBe("normalized");
    expect(fleet.fleetId).toBe("fleet-recorded");
    expect(fleet.rows.map((row) => row.symbol)).toEqual(["XLK", "VXZ", "MTUM"]);
    expect(fleet.rows[0]).toMatchObject({ price: 183.74, returnPct: -0.468026, coverage: "used", candidateState: "OBSERVE", candidateReasons: ["Recorded reason"] });
    expect(fleet.rows[1]).toMatchObject({ coverage: "excluded", candidateState: null });
    expect(fleet.rows[2]).toMatchObject({ price: null, returnPct: null, coverage: "excluded", candidateState: "WATCH" });
    expect(fleet.rows.some((row) => row.symbol === "AAPL")).toBe(false);
    expect(JSON.stringify(test.documents)).toBe(before);
  });

  it("never fills absent fields with zero, prices from candidates, or company names", () => {
    const test = fixture();
    test.documents.oracle_normalized_snapshot!.symbols = [{ symbol: "XLK", price: "123", return_pct: null }];
    const row = createRecordedFleetOverview(test.view()).rows[0];
    expect(row.price).toBeNull();
    expect(row.returnPct).toBeNull();
    expect(row.timestamp).toBeNull();
    expect(row).not.toHaveProperty("name");
  });

  it("does not join classifications from a different or unidentified snapshot", () => {
    const test = fixture();
    test.documents.oracle_measurement_diagnostics!.normalized_snapshot_id = "different";
    delete test.documents.council_candidate_evidence!.normalized_snapshot_id;
    const fleet = createRecordedFleetOverview(test.view());
    expect(fleet.rows.every((row) => row.coverage === "not-recorded" && row.candidateState === null)).toBe(true);
    expect(fleet.notes).toHaveLength(2);
  });

  it("falls back explicitly to diagnostic/candidate records without manufacturing observed prices", () => {
    const test = fixture();
    test.evidence.set("oracle_normalized_snapshot", { ...test.evidence.get("oracle_normalized_snapshot")!, status: "UNAVAILABLE", document: null });
    const fleet = createRecordedFleetOverview(test.view());
    expect(fleet.source).toBe("fallback");
    expect(fleet.rows.map((row) => row.symbol)).toEqual(["XLK", "VXZ", "MTUM", "AAPL"]);
    expect(fleet.rows.every((row) => row.price === null && row.returnPct === null && row.timestamp === null)).toBe(true);
    expect(fleet.observedAt).toBeNull();
    expect(fleet.links.some((link) => link.reference.name === "oracle_normalized_snapshot")).toBe(false);
  });

  it("shows an individual fallback source even if its snapshot ID is unavailable, without joining unrelated records", () => {
    const test = fixture();
    test.evidence.delete("oracle_normalized_snapshot");
    delete test.documents.oracle_measurement_diagnostics!.normalized_snapshot_id;
    const fleet = createRecordedFleetOverview(test.view());
    expect(fleet.source).toBe("fallback");
    expect(fleet.rows.map((row) => row.symbol)).toEqual(["XLK", "VXZ", "MTUM"]);
    expect(fleet.rows[0].coverage).toBe("used");
    expect(fleet.rows.every((row) => row.candidateState === null)).toBe(true);
  });

  it("does not silently deduplicate an ambiguous observed list or conflicting coverage flags", () => {
    const test = fixture();
    test.documents.oracle_normalized_snapshot!.symbols = [{ symbol: "XLK" }, { symbol: "XLK" }];
    test.documents.oracle_measurement_diagnostics!.items = [{ symbol: "XLK", used: true, excluded: true }];
    const fleet = createRecordedFleetOverview(test.view());
    expect(fleet.source).toBe("fallback");
    expect(fleet.notes[0]).toMatch(/no usable unique symbol list/);
    expect(fleet.rows[0].coverage).toBe("conflicting");
  });

  it("reports mismatched recorded counts without adding imaginary rows", () => {
    const test = fixture();
    test.documents.oracle_normalized_snapshot!.symbol_count = 99;
    const fleet = createRecordedFleetOverview(test.view());
    expect(fleet.rows).toHaveLength(3);
    expect(fleet.notes).toContain("The recorded symbol count differs from the listed rows; this table shows the supplied rows without inventing missing symbols.");
  });

  it("keeps a recorded empty snapshot empty instead of substituting candidate membership", () => {
    const test = fixture();
    test.documents.oracle_normalized_snapshot!.symbols = [];
    test.documents.oracle_normalized_snapshot!.symbol_count = 0;
    const fleet = createRecordedFleetOverview(test.view());
    expect(fleet.source).toBe("normalized");
    expect(fleet.rows).toEqual([]);
  });

  it("uses only safe named evidence links and never parses configured membership from YAML", () => {
    const test = fixture();
    expect(createRecordedFleetOverview(test.view()).links).toHaveLength(4);
    test.bundle.artifactIndex = new Map([["oracle_fleet_input", artifact("oracle_fleet_input", "../secrets.yaml")]]);
    test.evidence.set("oracle_normalized_snapshot", { ...test.evidence.get("oracle_normalized_snapshot")!, reference: artifact("wrong_name", "oracle/normalized.json") });
    expect(createRecordedFleetOverview(test.view()).links).toHaveLength(2);
  });

  it("returns honest absence when no usable evidence is loaded", () => {
    const bundle = createMissionBundleFixture();
    const fleet = createRecordedFleetOverview(createMissionViewModel(bundle));
    expect(fleet).toMatchObject({ source: "none", rows: [], links: [], fleetId: null, observedAt: null });
  });
});
