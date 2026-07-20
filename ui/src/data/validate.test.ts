import { describe, expect, it } from "vitest";
import { createMissionBundleFixture } from "../test/missionFixture";
import {
  PresentationContractError,
  isMissionRelativePath,
  parseCaptainsLog,
  parseDemoManifest,
  parseMissionSnapshot,
  parseMissionSummary,
  validateMissionBundleContracts,
} from "./validate";

function raw<T>(value: T): unknown {
  return JSON.parse(JSON.stringify(value));
}

describe("canonical presentation validation", () => {
  it("accepts the correlated approved presentation contracts", () => {
    const bundle = createMissionBundleFixture();
    const contracts = {
      summary: parseMissionSummary(raw(bundle.summary)),
      captainsLog: parseCaptainsLog(raw(bundle.captainsLog)),
      manifest: parseDemoManifest(raw(bundle.manifest)),
      snapshot: parseMissionSnapshot(raw(bundle.snapshot)),
    };

    expect(validateMissionBundleContracts(contracts).summary.final_outcome).toBe("APPROVED");
    expect(contracts.summary.approval_scope).toBe("NAVIGATOR_SHADOW_HANDOFF");
  });

  it("rejects unsupported schemas and unknown fields", () => {
    const bundle = createMissionBundleFixture();
    const summary = raw(bundle.summary) as Record<string, unknown>;
    summary.schema_version = "blackpod.mission_summary.v999";
    expect(() => parseMissionSummary(summary)).toThrow(PresentationContractError);

    const log = raw(bundle.captainsLog) as Record<string, unknown>;
    log.invented = true;
    expect(() => parseCaptainsLog(log)).toThrow(/unknown invented/);
  });

  it("rejects outcome, correlation, and safety-policy conflicts", () => {
    const bundle = createMissionBundleFixture();
    const manifest = raw(bundle.manifest) as Record<string, unknown>;
    manifest.final_outcome = "HELD";
    expect(() => parseDemoManifest(manifest)).toThrow(/scenario and final outcome/);

    const unsafe = raw(bundle.manifest) as Record<string, unknown>;
    unsafe.allowed_operations = ["VALIDATE", "PLAN_ONLY", "SUBMIT_ORDER"];
    expect(() => parseDemoManifest(unsafe)).toThrow(/SHADOW safety policy/);

    expect(() => validateMissionBundleContracts({
      summary: bundle.summary,
      captainsLog: { ...bundle.captainsLog, mission_id: "mission-conflict" },
      manifest: bundle.manifest,
      snapshot: bundle.snapshot,
    })).toThrow(/mission correlation/);
  });

  it("accepts only mission-relative evidence paths", () => {
    expect(isMissionRelativePath("oracle/attempt-0001/oracle_report_live.json")).toBe(true);
    expect(isMissionRelativePath("/Users/demo/report.json")).toBe(false);
    expect(isMissionRelativePath("../report.json")).toBe(false);
    expect(isMissionRelativePath("C:\\demo\\report.json")).toBe(false);
  });
});

