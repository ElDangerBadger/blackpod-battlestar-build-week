import { describe, expect, it } from "vitest";
import { createMissionBundleFixture } from "../test/missionFixture";
import { createMissionViewModel } from "./viewModel";

describe("mission presentation view model", () => {
  it("projects canonical values without changing outcome or approval scope", () => {
    const viewModel = createMissionViewModel(createMissionBundleFixture());

    expect(viewModel.status.governorDisposition).toBe("PROCEED");
    expect(viewModel.status.operatorResult).toBe("APPROVED_FOR_HANDOFF");
    expect(viewModel.status.navigatorPlanStatus).toBe("CREATED");
    expect(viewModel.status.outcome).toBe("APPROVED");
    expect(viewModel.status.approvalScope).toBe("NAVIGATOR_SHADOW_HANDOFF");
  });

  it("preserves the exact SHADOW safety boundary and log order", () => {
    const viewModel = createMissionViewModel(createMissionBundleFixture());

    expect(viewModel.safety.displayStatement).toMatch(/SHADOW handoff only/);
    expect(viewModel.safety.allowedOperations).toEqual(["VALIDATE", "PLAN_ONLY"]);
    expect(viewModel.safety.prohibitedOperations).toEqual([
      "SUBMIT_ORDER",
      "CANCEL_ORDER",
      "MODIFY_PORTFOLIO",
      "BROKER_CALL",
    ]);
    expect(viewModel.captainsLog.map((entry) => entry.stage)).toEqual([
      "HARBORMASTER",
      "ORACLE",
      "MODELDOCK",
      "COUNCIL",
      "GOVERNOR",
      "OPERATOR",
      "NAVIGATOR",
      "MISSION",
    ]);
  });
});

