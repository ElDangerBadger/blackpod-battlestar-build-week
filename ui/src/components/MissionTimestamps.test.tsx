import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CaptainsLog } from "./CaptainsLog";
import { StatusPanel, type StatusPanelProps } from "./StatusPanel";

const statusProps: StatusPanelProps = {
  presentationMode: "LIVE",
  symbol: "AAPL",
  companyName: null,
  timeframe: null,
  marketStatus: null,
  latestCompletedBar: null,
  mode: "LIVE",
  outcome: "INCOMPLETE",
  phase: "ORACLE",
  missionId: "mission-live-timestamps",
  timestamp: "2026-07-19T01:34:28Z",
  approvalScope: null,
  snapshotCount: 1,
  modeldockMode: "NOT_RECORDED",
  modeldockStatus: "NOT_STARTED",
  activeMilestone: "ORACLE",
  activeStatus: "NOT_STARTED",
};

const timestamps = [
  "2026-07-19T01:34:28Z",
  "2026-07-19T01:34:28.045Z",
  "2026-07-19T01:34:28.045047Z",
  "2026-07-19T01:34:28.045047123Z",
];

describe("compact recorded mission clocks", () => {
  it.each(timestamps)("keeps the status clock compact for %s", (timestamp) => {
    const { container } = render(<StatusPanel {...statusProps} timestamp={timestamp} />);
    const clock = container.querySelector<HTMLElement>(".status-time")!;

    expect(within(clock).getByText("2026-07-19")).toBeInTheDocument();
    expect(within(clock).getByText("01:34 UTC")).toBeInTheDocument();
    expect(clock).not.toHaveTextContent(timestamp);
  });

  it.each(timestamps)("keeps the log clock compact without rewriting %s", (timestamp) => {
    const entries = [{
      stage: "HARBORMASTER", status: "SUCCEEDED", timestamp,
      summary: "Mission initialized.", evidenceCount: 1,
    }];
    render(<CaptainsLog entries={entries} revealedStages={new Set(["HARBORMASTER"])} />);

    expect(screen.getByText("01:34").closest("time")).toHaveAttribute("datetime", timestamp);
    expect(entries[0].timestamp).toBe(timestamp);
  });

  it("does not relabel a non-UTC offset as UTC", () => {
    const timestamp = "2026-07-18T18:34:28.045047-07:00";
    const { container } = render(<StatusPanel {...statusProps} timestamp={timestamp} />);
    const clock = container.querySelector<HTMLElement>(".status-time")!;

    expect(within(clock).getByText(timestamp)).toBeInTheDocument();
    expect(within(clock).queryByText("18:34 UTC")).not.toBeInTheDocument();
  });
});
