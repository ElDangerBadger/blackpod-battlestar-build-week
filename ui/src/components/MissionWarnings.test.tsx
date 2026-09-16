import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { explainMissionWarning, MissionWarnings } from "./MissionWarnings";

describe("MissionWarnings", () => {
  it("explains known notices while preserving their exact recorded text", () => {
    const warnings = Object.freeze([
      "EXCLUDED_ORACLE_SNAPSHOT_SYMBOLS:VXZ,IWF,IWD",
      "MISSING_PRIOR_ORACLE_MEASUREMENTS",
      "Mandate is valid but does not permit action: READ_ONLY_DATA_RUN_NO_TRADING_AUTHORITY",
    ]);
    const before = JSON.stringify(warnings);
    render(<MissionWarnings warnings={warnings} />);

    expect(screen.getByText(/3 recorded notices/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Some symbols were left out of Oracle's analysis" })).toBeInTheDocument();
    expect(screen.getByText("Excluded symbols: VXZ, IWF, IWD.")).toBeInTheDocument();
    expect(screen.getByText(/does not mean all current measurements are missing/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "This mission was authorized for analysis only" })).toBeInTheDocument();
    expect(screen.getByText(/blocked action decision is not itself a processing failure/)).toBeInTheDocument();
    expect(screen.getAllByText("Original warning · exact wording")).toHaveLength(3);
    warnings.forEach((warning) => expect(screen.getByText(warning, { selector: "code" })).toBeInTheDocument());
    expect(JSON.stringify(warnings)).toBe(before);
  });

  it("keeps unknown warning text literal without guessing a meaning or injecting markup", () => {
    const raw = "UNRECOGNIZED_FLAG:<img src=x onerror=alert(1)>_LONG_VALUE";
    const { container } = render(<MissionWarnings warnings={[raw]} />);
    const item = screen.getByRole("listitem");

    expect(within(item).getByRole("heading", { name: "Additional recorded warning" })).toBeInTheDocument();
    expect(within(item).getAllByText(raw)).toHaveLength(2);
    expect(within(item).getByText(/No plain-language explanation is mapped/)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(explainMissionWarning(raw).meaning).toBe(raw);
  });

  it("does not infer exclusions from an empty symbol suffix", () => {
    expect(explainMissionWarning("EXCLUDED_ORACLE_SNAPSHOT_SYMBOLS:")).toMatchObject({
      title: "Additional recorded warning",
      meaning: "EXCLUDED_ORACLE_SNAPSHOT_SYMBOLS:",
    });
  });

  it("recognizes only exact analysis-only mandate values", () => {
    expect(explainMissionWarning("READ_ONLY_DATA_RUN_NO_TRADING_AUTHORITY").title).toBe("This mission was authorized for analysis only");
    expect(explainMissionWarning("READ_ONLY_DATA_RUN_NO_TRADING_AUTHORITY_CHANGED").title).toBe("Additional recorded warning");
  });

  it("presents one notice without plural wording", () => {
    render(<MissionWarnings warnings={["MISSING_PRIOR_ORACLE_MEASUREMENTS"]} />);
    expect(screen.getByText(/1 recorded notice to understand/)).toBeInTheDocument();
  });

  it("does not manufacture notices when the mission recorded none", () => {
    render(<MissionWarnings warnings={[]} />);
    expect(screen.getByText("No warnings are recorded in this mission.")).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });
});
