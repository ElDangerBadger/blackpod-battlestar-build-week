import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SystemsPanel, type SystemsPanelProps } from "./SystemsPanel";

const props: SystemsPanelProps = {
  presentationMode: "LIVE", warnings: ["MISSING_PRIOR_ORACLE_MEASUREMENTS"],
  governorDisposition: "BLOCKED", operatorResult: null, approvalScope: null,
  modeldockMode: "LIVE", provider: "mlx", model: "recorded-model", traceId: "recorded-trace",
  latencyMs: 12, lastSuccessfulInference: "2026-09-15T23:05:00Z",
  modeldockAvailability: "Recorded inference provenance", mocked: false,
  portfolio: {
    status: "NOT_CONFIGURED", mode: null, sourceIdentity: null, capturedAt: null,
    accountType: null, currency: null, positionCount: 0, snapshot: null,
  },
  allowedOperations: ["VALIDATE", "PLAN_ONLY"],
  prohibitedOperations: ["SUBMIT_ORDER", "CANCEL_ORDER", "MODIFY_PORTFOLIO", "BROKER_CALL"],
};

describe("SystemsPanel read-only expansion triggers", () => {
  it("opens each right-panel module with a native keyboard-focusable button", () => {
    const onExpand = vi.fn();
    render(<SystemsPanel {...props} onExpand={onExpand} />);
    const modules = [
      ["Open watchlist and warnings", "watchlist"], ["Open risk and governance", "governance"],
      ["Open Governor disposition", "governor"], ["Open portfolio exposure", "portfolio"],
      ["Open ModelDock provenance", "modeldock"], ["Open model routing", "model-routing"],
      ["Open safety boundary", "safety"],
    ];
    expect(screen.getAllByRole("button")).toHaveLength(7);
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
    expect(onExpand).toHaveBeenCalledTimes(7);
  });

  it("preserves displayed evidence and safety text without granting authority", () => {
    const before = JSON.stringify(props);
    const { container } = render(<SystemsPanel {...props} onExpand={vi.fn()} activePanel="safety" />);
    expect(screen.getByRole("button", { name: "Open safety boundary" })).toHaveAttribute("aria-expanded", "true");
    expect(container.querySelectorAll('[aria-expanded="true"]')).toHaveLength(1);
    expect(screen.getByText("PROCEED is not approval.")).toBeInTheDocument();
    expect(screen.getByText("No execution authority.")).toBeInTheDocument();
    expect(screen.getByText("Not configured — no illustrative holdings shown.")).toBeInTheDocument();
    expect(screen.getByText("recorded-model")).toBeInTheDocument();
    expect(screen.getByText("12 ms")).toBeInTheDocument();
    expect(screen.getByText(/VALIDATE · PLAN_ONLY/)).toBeInTheDocument();
    expect(screen.getByText(/SUBMIT_ORDER · CANCEL_ORDER · MODIFY_PORTFOLIO · BROKER_CALL/)).toBeInTheDocument();
    expect(container.querySelector("button button")).toBeNull();
    expect(JSON.stringify(props)).toBe(before);
  });

  it("shows captured portfolio facts without adding holdings or mutation controls", () => {
    render(<SystemsPanel {...props} onExpand={vi.fn()} portfolio={{
      ...props.portfolio, status: "CAPTURED", mode: "READ_ONLY", sourceIdentity: "captured-portfolio",
      capturedAt: "2026-09-15T22:00:00Z", positionCount: 2,
    }} />);
    expect(screen.getByText("captured-portfolio")).toBeInTheDocument();
    expect(screen.getByText("2026-09-15 22:00Z")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /buy|sell|execute|approve/i })).not.toBeInTheDocument();
  });

  it("does not expose dead buttons when the expansion handler is absent", () => {
    render(<SystemsPanel {...props} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByText("Open ↗")).not.toBeInTheDocument();
    expect(screen.getByText("No execution authority.")).toBeInTheDocument();
  });
});
