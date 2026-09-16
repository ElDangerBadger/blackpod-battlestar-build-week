import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { StatusPanel, type StatusPanelProps } from "./StatusPanel";

const props: StatusPanelProps = {
  presentationMode: "LIVE", symbol: "AAPL", companyName: "Apple Inc.",
  timeframe: "1d", marketStatus: "Captured", latestCompletedBar: "2026-09-15T00:00:00Z",
  mode: "LIVE", outcome: "HELD", phase: "GOVERNOR", missionId: "mission-live-aapl-002",
  timestamp: "2026-09-15T23:06:32Z", approvalScope: null, snapshotCount: 9,
  modeldockMode: "LIVE", modeldockStatus: "SUCCEEDED", activeMilestone: "GOVERNOR", activeStatus: "BLOCKED",
};

describe("StatusPanel read-only expansion triggers", () => {
  it("opens each top-panel module using a native, labelled button", () => {
    const onExpand = vi.fn();
    render(<StatusPanel {...props} onExpand={onExpand} />);
    const modules = [
      ["Open market context", "market"], ["Open fleet status", "fleet"],
      ["Open ModelDock provenance", "modeldock"], ["Open timeframe details", "timeframe"],
      ["Open mission details", "mission"], ["Open market timing", "market-timing"],
      ["Open mission time", "mission-time"], ["Open approval scope", "approval"],
    ];
    expect(screen.getAllByRole("button")).toHaveLength(8);
    for (const [label, panel] of modules) {
      const button = screen.getByRole("button", { name: label });
      expect(button.tagName).toBe("BUTTON");
      expect(button).toHaveAttribute("type", "button");
      expect(button).toHaveAttribute("aria-haspopup", "dialog");
      expect(button).toHaveAttribute("aria-expanded", "false");
      expect(button.tabIndex).toBe(0);
      button.focus();
      expect(button).toHaveFocus();
      fireEvent.click(button);
      expect(onExpand).toHaveBeenLastCalledWith(panel);
    }
    expect(onExpand).toHaveBeenCalledTimes(8);
  });

  it("marks only the selected module expanded and retains every existing fact", () => {
    const before = JSON.stringify(props);
    const { container, rerender } = render(<StatusPanel {...props} onExpand={vi.fn()} activePanel="fleet" />);
    expect(screen.getByRole("button", { name: "Open fleet status" })).toHaveAttribute("aria-expanded", "true");
    expect(container.querySelectorAll('[aria-expanded="true"]')).toHaveLength(1);
    expect(screen.getByText("HELD · GOVERNOR")).toBeInTheDocument();
    expect(screen.getByText("AAPL · correlation")).toBeInTheDocument();
    expect(screen.getByText("Navigator reference: Apple Inc. · 1d")).toBeInTheDocument();
    expect(screen.getByText("9 snapshots")).toBeInTheDocument();
    expect(screen.getByText("mission-live-aapl-002")).toBeInTheDocument();
    expect(screen.getByText("23:06 UTC")).toBeInTheDocument();
    expect(screen.getByText("Not present")).toBeInTheDocument();
    expect(container.querySelector("button button")).toBeNull();
    expect(JSON.stringify(props)).toBe(before);
    rerender(<StatusPanel {...props} onExpand={vi.fn()} activePanel={null} />);
    expect(container.querySelectorAll('[aria-expanded="true"]')).toHaveLength(0);
  });

  it("keeps the legacy read-only surface static when no expansion handler exists", () => {
    render(<StatusPanel {...props} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByText("Open ↗")).not.toBeInTheDocument();
    expect(screen.getByText("HELD · GOVERNOR")).toBeInTheDocument();
  });
});
