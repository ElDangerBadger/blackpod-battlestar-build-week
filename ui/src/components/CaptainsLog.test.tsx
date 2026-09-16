import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CaptainsLog, type CaptainsLogEntryView } from "./CaptainsLog";

const entries: readonly CaptainsLogEntryView[] = [
  { stage: "ORACLE", status: "SUCCEEDED", timestamp: "2026-09-15T18:02:03.123456Z", summary: "Exact Oracle summary.", evidenceCount: 2 },
  { stage: "COUNCIL", status: "SUCCEEDED", timestamp: "2026-09-15T18:03:04Z", summary: "Exact Council summary.", evidenceCount: 1 },
];

describe("Captain's Log paper preview", () => {
  it("provides one full-paper button with the existing accessible name and an Open cue", () => {
    const onFocus = vi.fn();
    const { container } = render(<CaptainsLog entries={entries} revealedStages={new Set(["ORACLE", "COUNCIL"])} onFocus={onFocus} />);
    const button = screen.getByRole("button", { name: "Focus Captain's Log" });

    expect(button).toHaveClass("captains-log-paper-button");
    expect(button.parentElement).toHaveClass("captains-log-preview", "is-interactive");
    expect(container.querySelectorAll("button")).toHaveLength(1);
    expect(button.querySelector("button")).toBeNull();
    expect(screen.getByText("Open ↗")).toBeInTheDocument();
    expect(button).toHaveAttribute("type", "button");
    expect(button).toHaveAttribute("aria-haspopup", "dialog");
    button.focus();
    expect(button).toHaveFocus();
    fireEvent.click(button);
    expect(onFocus).toHaveBeenCalledTimes(1);
  });

  it("preserves revealed stages, exact summaries, evidence counts, and timestamp attributes", () => {
    const { container } = render(<CaptainsLog entries={entries} revealedStages={new Set(["ORACLE"])} onFocus={() => {}} />);

    expect(screen.getByText("Exact Oracle summary.")).toBeInTheDocument();
    expect(screen.queryByText("Exact Council summary.")).not.toBeInTheDocument();
    expect(screen.getByText("2 evidence records")).toBeInTheDocument();
    expect(screen.getByText("18:02").closest("time")).toHaveAttribute("datetime", entries[0].timestamp);
    expect(container.querySelectorAll("li.is-revealed")).toHaveLength(1);
    expect(container.querySelectorAll("li.is-concealed")).toHaveLength(1);
    expect(entries[1].summary).toBe("Exact Council summary.");
  });

  it("retains focus state without exposing a dead control when no callback is provided", () => {
    const { container, rerender } = render(<CaptainsLog entries={entries} revealedStages={new Set(["ORACLE"])} focused onFocus={() => {}} />);
    expect(container.querySelector(".captains-log-preview")).toHaveClass("is-focused");
    expect(screen.getByRole("button", { name: "Focus Captain's Log" })).toHaveAttribute("aria-expanded", "true");

    rerender(<CaptainsLog entries={entries} revealedStages={new Set(["ORACLE"])} />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByText("Open ↗")).toBeNull();
    expect(screen.getByText("Exact Oracle summary.")).toBeInTheDocument();
  });
});
