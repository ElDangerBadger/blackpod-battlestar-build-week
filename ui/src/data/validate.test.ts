import { describe, expect, it } from "vitest";
import { createMissionBundleFixture } from "../test/missionFixture";
import {
  PresentationContractError,
  isMissionRelativePath,
  parseCaptainsLog,
  parseArtifactReference,
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

  it("accepts only the three canonical v1 stage variants and omitted optional snapshot sections", () => {
    const source = raw(createMissionBundleFixture().snapshot) as Record<string, unknown>;
    for (const field of ["components", "operator", "navigator", "approval_scope"]) delete source[field];
    const stages = source.stages as Record<string, Record<string, unknown>>;
    stages.harbormaster = { status: "SUCCEEDED", native_state: "INITIALIZED" };
    delete stages.oracle.modeldock_calls;
    const parsed = parseMissionSnapshot(source);
    expect(parsed.components).toEqual({});
    expect(parsed.stages.harbormaster.inputs).toEqual([]);
    expect(parsed.stages.oracle.modeldock_calls).toEqual([]);
    expect(parsed.operator.action_status).toBe("NOT_STARTED");
    expect(parsed.navigator.mode).toBeNull();
    expect(parsed.navigator.allowed_operations).toEqual([]);
    expect(parsed.approval_scope).toBeNull();
    expect(() => parseMissionSnapshot({ ...source, surprise: true })).toThrow(/unknown surprise/);
    stages.harbormaster.inputs = [];
    expect(() => parseMissionSnapshot(source)).toThrow(/missing/);
    stages.harbormaster = { status: "SUCCEEDED", native_state: "INITIALIZED", extra: true };
    expect(() => parseMissionSnapshot(source)).toThrow(/unknown extra/);
  });

  it("accepts legacy operator routing only with empty legacy action fields", () => {
    const source = raw(createMissionBundleFixture().snapshot) as Record<string, unknown>;
    source.operator = { route: "PENDING_APPROVAL", action: null, result: null, operator_id: null, acted_at: null };
    const parsed = parseMissionSnapshot(source);
    expect(parsed.operator.route).toBe("PENDING_APPROVAL");
    expect(parsed.operator.action_status).toBe("NOT_STARTED");
    source.operator = { ...(source.operator as object), action: "APPROVE_HANDOFF" };
    expect(() => parseMissionSnapshot(source)).toThrow(/legacy operator action fields must remain null/);
  });

  it("does not treat explicitly null optional objects as omitted v1 sections", () => {
    const source = createMissionBundleFixture().snapshot;
    for (const field of ["components", "operator", "navigator"]) {
      expect(() => parseMissionSnapshot({ ...source, [field]: null })).toThrow(/must be an object/);
    }
  });

  it("accepts the canonical three-field historical reference while rejecting partial or unknown metadata", () => {
    const legacy = { name: "mission_request", path: "request/mission_request.json", sha256: "a".repeat(64) };
    expect(parseArtifactReference(legacy)).toEqual({ ...legacy, producer: null, byte_size: null, schema_version: null, observed_at: null });
    expect(() => parseArtifactReference({ ...legacy, producer: "harbormaster" })).toThrow(/missing/);
    expect(() => parseArtifactReference({ ...legacy, invented: "metadata" })).toThrow(/unknown invented/);
  });
});
