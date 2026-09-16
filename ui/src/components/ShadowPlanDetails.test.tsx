import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { artifact, createMissionBundleFixture } from "../test/missionFixture";
import { createMissionViewModel } from "../data/viewModel";
import { ShadowPlanDetails } from "./ShadowPlanDetails";

describe("Shadow Plan details", () => {
  it("explains the no-trade run without adding activation or implying a plan exists", () => {
    const mission = createMissionViewModel(createMissionBundleFixture());
    mission.status.navigatorPlanStatus = null;
    mission.status.operatorResult = null;
    mission.status.approvalScope = null;
    mission.status.governorDisposition = "BLOCKED";
    mission.stages.navigator.technicalStatus = "NOT_STARTED";
    mission.warnings = ["Mandate is valid but does not permit action: READ_ONLY_DATA_RUN_NO_TRADING_AUTHORITY"];
    const before = JSON.stringify(mission);
    const open = vi.fn();
    render(<ShadowPlanDetails mission={mission} onOpenBook={open} />);
    expect(screen.getByText("No SHADOW plan artifact is available for this mission.")).toBeInTheDocument();
    expect(screen.getByText(/explicitly authorized for analysis only/)).toBeInTheDocument();
    expect(screen.getByText(/Their availability does not mean an operational plan was created/)).toBeInTheDocument();
    expect(screen.getByText(/There is no activation or approval control here/)).toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Read full Navigator ledger" }));
    expect(open).toHaveBeenCalledOnce();
    expect(JSON.stringify(mission)).toBe(before);
  });

  it("renders supplied plan observations and the exact original artifact", () => {
    const bundle = createMissionBundleFixture();
    const plan = { plan_id: "plan-1", observations: ["Recorded market context"], proposed_next_analytical_steps: ["Review the supplied evidence"], planning_status: "CREATED" };
    bundle.evidence = new Map(bundle.evidence).set("navigator_shadow_plan", {
      name: "navigator_shadow_plan", reference: artifact("navigator_shadow_plan", "navigator/plan.json"),
      status: "LOADED", document: plan, message: null,
    });
    const mission = createMissionViewModel(bundle);
    render(<ShadowPlanDetails mission={mission} onOpenBook={() => {}} />);
    expect(screen.getByText("A captured SHADOW plan is available to read.")).toBeInTheDocument();
    expect(screen.getByText("Recorded market context")).toBeInTheDocument();
    expect(screen.getByText("Review the supplied evidence")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open original SHADOW plan artifact" })).toHaveAttribute("href", `${mission.baseUrl}navigator/plan.json`);
    expect(screen.getByText("Original plan · exact recorded values").closest("details")).not.toHaveAttribute("open");
    expect(screen.queryByText(/This run was explicitly authorized for analysis only/)).not.toBeInTheDocument();
  });
});
