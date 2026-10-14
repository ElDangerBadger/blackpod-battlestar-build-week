import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createShadowExperimentFixture } from "../test/shadowExperimentFixture";
import { useShadowExperiment, type ShadowExperimentState } from "../data/useShadowExperiment";
import { ShadowExperiment, ShadowExperimentPage } from "./ShadowExperiment";

vi.mock("../data/useShadowExperiment", () => ({ useShadowExperiment: vi.fn() }));
const hook = vi.mocked(useShadowExperiment);
function ready(rows = false): ShadowExperimentState { return { status: "READY", feed: createShadowExperimentFixture(rows), message: "", refreshing: false, refresh: vi.fn() }; }
beforeEach(() => { vi.clearAllMocks(); hook.mockReturnValue(ready()); });
describe("one read-only shadow experiment", () => {
  it("shows frozen hypothesis and every opportunity without inventing outcomes", () => {
    render(<ShadowExperiment />);
    expect(screen.getByRole("heading", { name: "One hypothesis. One frozen experiment." })).toBeInTheDocument();
    expect(screen.getByText("synthetic-shadow-experiment")).toBeInTheDocument();
    const table = screen.getByRole("table"); expect(within(table).getAllByRole("row")).toHaveLength(61);
    expect(within(table).getAllByText("Awaiting prediction")).toHaveLength(60);
    expect(screen.getByText("0 / 60")).toBeInTheDocument();
    expect(screen.getByText(/No net performance or realized trade P&L/)).toBeInTheDocument();
    expect(screen.getByText(/not a statistical power calculation/, { selector: "li", exact: false })).toBeInTheDocument();
    expect(screen.getAllByText("Unavailable").length).toBeGreaterThan(0);
  });
  it("presents source-linked candidate and abstention separately from gross outcomes", () => {
    hook.mockReturnValue(ready(true)); render(<ShadowExperiment />);
    expect(screen.getByText("observational candidate")).toBeInTheDocument();
    expect(screen.getByText("abstain nonnegative return")).toBeInTheDocument();
    expect(screen.getByText("observed gross proxy only")).toBeInTheDocument();
    expect(screen.getByText("not applicable abstention")).toBeInTheDocument();
    expect(screen.getByText("Candidate 1.00%")).toBeInTheDocument();
    expect(screen.getByText("Control 0.50%")).toBeInTheDocument();
    expect(screen.getByText("Excess 0.50%")).toBeInTheDocument();
    expect(screen.getByText("Cash 0.00%")).toBeInTheDocument();
    expect(screen.getByText(/No trading authority/)).toBeInTheDocument();
  });
  it("exposes only manual reading, no trading, approval or collection actions", () => {
    const state = ready(); hook.mockReturnValue(state); render(<ShadowExperiment />);
    expect(screen.getAllByRole("button")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Refresh saved records" })); expect(state.refresh).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: /trade|approve|collect|start|run/i })).not.toBeInTheDocument();
  });
  it.each(["LOADING", "NOT_CONFIGURED", "UNAVAILABLE", "DISABLED"] as const)("shows %s with no substituted rows", (status) => {
    hook.mockReturnValue({ ...ready(), status, feed: null, message: "No saved records." }); render(<ShadowExperiment />);
    expect(screen.getByRole("status")).toBeInTheDocument(); expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
  it("disables refresh when busy or disabled", () => {
    hook.mockReturnValue({ ...ready(), refreshing: true }); const { rerender } = render(<ShadowExperiment />);
    expect(screen.getByRole("button")).toBeDisabled(); hook.mockReturnValue(ready()); rerender(<ShadowExperiment enabled={false} />);
    expect(screen.getByRole("button")).toBeDisabled(); expect(hook).toHaveBeenLastCalledWith({ enabled: false });
  });
  it("provides a direct responsive page independent of any mission", () => {
    render(<ShadowExperimentPage />);
    expect(screen.getByRole("link", { name: "Return to Captain’s Cabin" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("main")).toHaveClass("shadow-experiment-page");
  });
});
