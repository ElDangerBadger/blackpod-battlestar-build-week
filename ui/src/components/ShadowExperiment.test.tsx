import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createShadowExperimentFixture } from "../test/shadowExperimentFixture";
import { useShadowExperiment, type ShadowExperimentState } from "../data/useShadowExperiment";
import { ShadowExperiment, ShadowExperimentPage } from "./ShadowExperiment";

vi.mock("../data/useShadowExperiment", () => ({ useShadowExperiment: vi.fn() }));
const hook = vi.mocked(useShadowExperiment);
function ready(rows = false): ShadowExperimentState { return { status: "READY", feed: createShadowExperimentFixture(rows), message: "", refreshing: false, refresh: vi.fn() }; }
function comparison() { return screen.getByRole("heading", { name: "Did the rule beat the control?" }).closest("section")!; }
beforeEach(() => { vi.clearAllMocks(); vi.stubEnv("VITE_SHADOW_HISTORICAL_REPORT_URL", ""); hook.mockReturnValue(ready()); });
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

describe("one read-only shadow experiment", () => {
  it("shows all 60 scheduled checks graphically without inventing predictions or returns", () => {
    const state = ready(); hook.mockReturnValue(state); render(<ShadowExperiment />);
    expect(screen.getByRole("heading", { name: "Reversal experiment" })).toBeInTheDocument();
    const progress = screen.getByRole("region", { name: "30-session progress" });
    expect(within(progress).getAllByRole("img")).toHaveLength(60);
    for (const session of state.feed!.experiment!.protocol.sessions) {
      for (const symbol of ["QQQ", "SPY"]) expect(within(progress).getByRole("img", { name: `${session.date} ${symbol}: Awaiting prediction` })).toBeInTheDocument();
    }
    expect(screen.getByText("No predictions recorded yet.")).toBeInTheDocument();
    expect(within(comparison()).getByText("Waiting for measured outcomes")).toBeInTheDocument();
    expect(within(comparison()).queryByText(/[+-]?0\.00(?:%| pp)/)).not.toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /^Mean gross difference versus control/ })).not.toBeInTheDocument();
  });

  it("shows recorded checks first and reveals the full frozen schedule on request", () => {
    hook.mockReturnValue(ready(true)); render(<ShadowExperiment />);
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(within(table).queryByText("Awaiting prediction")).not.toBeInTheDocument();
    const checkbox = screen.getByRole("checkbox", { name: "Show all 60 scheduled checks" });
    expect(checkbox).not.toBeChecked(); fireEvent.click(checkbox);
    expect(checkbox).toBeChecked();
    expect(within(table).getAllByRole("row")).toHaveLength(61);
    expect(within(table).getAllByText("Awaiting prediction")).toHaveLength(58);
    fireEvent.click(checkbox); expect(within(table).getAllByRole("row")).toHaveLength(3);
  });

  it("shows the waiting schedule without manufacturing records when the cohort has not started", () => {
    render(<ShadowExperiment />);
    fireEvent.click(screen.getByRole("checkbox", { name: "Show all 60 scheduled checks" }));
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(61);
    expect(within(table).getAllByText("Awaiting prediction")).toHaveLength(60);
    expect(screen.queryByText("Candidate 0.00%")).not.toBeInTheDocument();
  });

  it("keeps candidates, abstentions and linked gross outcomes distinct", () => {
    const state = ready(true), view = state.feed!.experiment!; hook.mockReturnValue(state); render(<ShadowExperiment />);
    const progress = screen.getByRole("region", { name: "30-session progress" });
    const day = view.protocol.sessions[0].date;
    expect(within(progress).getByRole("img", { name: `${day} QQQ: Candidate` })).toBeInTheDocument();
    expect(within(progress).getByRole("img", { name: `${day} SPY: Abstained` })).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByText("Candidate", { exact: true })).toBeInTheDocument();
    expect(within(table).getByText("Abstained", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("Candidate 1.00%")).toBeInTheDocument();
    expect(screen.getByText("Control 0.50%")).toBeInTheDocument();
    expect(screen.getByText("Excess 0.50 pp")).toBeInTheDocument();
    expect(screen.getByText("Cash 0.00%")).toBeInTheDocument();
    expect(screen.getByText("observational candidate")).toBeInTheDocument();
    expect(screen.getByText("abstain nonnegative return")).toBeInTheDocument();
    expect(screen.getByText("NEGATIVE_COMPLETED_PROVIDER_CLOSE_RETURN")).toBeInTheDocument();
    expect(screen.getByText("FROZEN_NEGATIVE_CLOSE_CONDITION_NOT_MET")).toBeInTheDocument();
  });

  it.each([
    ["0.005", /\+?0\.50 pp/], ["-0.005", /[−-]0\.50 pp/], ["0", /\+?0\.00 pp/],
  ] as const)("presents the recorded difference %s against a zero control baseline", (excess, formatted) => {
    const state = ready(true); state.feed!.experiment!.summary.mean_gross_excess_over_control = excess;
    hook.mockReturnValue(state); render(<ShadowExperiment />);
    const section = within(comparison());
    expect(section.getByText("Rule average")).toBeInTheDocument();
    expect(section.getByText("Difference vs control")).toBeInTheDocument();
    expect(section.getByText(formatted, { selector: "dd" })).toBeInTheDocument();
    const graphic = section.getByRole("img", { name: /^Mean gross difference versus control/ });
    expect(graphic).toHaveAccessibleName(new RegExp(`^Mean gross difference versus control: ${excess.startsWith("-") ? "-" : ""}${excess === "0" ? "0\\.00" : "0\\.50"} pp$`));
    expect(within(graphic).getByText("0 pp · control")).toBeInTheDocument();
    expect(section.queryByText("Control average")).not.toBeInTheDocument();
  });

  it("keeps missing inputs and missed deadlines visible in both the grid and recorded rows", () => {
    const state = ready(true), view = state.feed!.experiment!, day = view.protocol.sessions[0].date;
    Object.assign(view.predictions[0], { status: "DEFER_MISSING_INPUT", signal_return: null, signal_close: null, previous_close: null, reason_codes: ["MISSING_SIGNAL_INPUT"] });
    Object.assign(view.predictions[1], { status: "MISSED_PREDICTION_DEADLINE", signal_return: null, signal_close: null, previous_close: null, reason_codes: ["MISSED_ADMISSION_DEADLINE"] });
    view.outcomes = [];
    Object.assign(view.summary, { candidate_count: 0, abstention_count: 0, missing_input_count: 1, missed_count: 1, observed_outcome_count: 0, mean_gross_return: null, mean_gross_excess_over_control: null, positive_gross_outcome_fraction: null });
    hook.mockReturnValue(state); render(<ShadowExperiment />);
    const progress = screen.getByRole("region", { name: "30-session progress" });
    expect(within(progress).getByRole("img", { name: `${day} QQQ: Missing input` })).toBeInTheDocument();
    expect(within(progress).getByRole("img", { name: `${day} SPY: Missed deadline` })).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByText("Missing input", { exact: true })).toBeInTheDocument();
    expect(within(table).getByText("Missed deadline", { exact: true })).toBeInTheDocument();
    expect(within(table).getByText("defer missing input")).toBeInTheDocument();
    expect(within(table).getByText("missed prediction deadline")).toBeInTheDocument();
    expect(within(table).getByText("MISSING_SIGNAL_INPUT")).toBeInTheDocument();
    expect(within(table).getByText("MISSED_ADMISSION_DEADLINE")).toBeInTheDocument();
    expect(within(comparison()).getByText("Waiting for measured outcomes")).toBeInTheDocument();
  });

  it("keeps the full frozen rules and provenance available in collapsed details", () => {
    render(<ShadowExperiment />);
    const summary = screen.getByText("Rules & evidence", { selector: "summary" }), details = summary.closest("details")!;
    expect(details).not.toHaveAttribute("open");
    expect(within(details).getByText("synthetic-shadow-experiment")).toBeInTheDocument();
    expect(within(details).getByText(/not a statistical power calculation/i)).toBeInTheDocument();
    expect(within(details).getByText(/No net performance or realized trade P&L/)).toBeInTheDocument();
    expect(within(details).getByText("blackpod.prospective_reversal_gross_proxy.v1")).toBeInTheDocument();
    expect(within(details).getByText("SYNTHETIC_PRESENTATION_FIXTURE_NOT_MARKET_EVIDENCE")).toBeInTheDocument();
  });

  it("exposes only manual reading and display controls, with no provider or mutation requests", () => {
    const state = ready(), before = JSON.stringify(state.feed), fetch = vi.fn(); vi.stubGlobal("fetch", fetch); hook.mockReturnValue(state); render(<ShadowExperiment />);
    fireEvent.click(screen.getByRole("button", { name: "Refresh saved records" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Show all 60 scheduled checks" }));
    expect(state.refresh).toHaveBeenCalledOnce();
    expect(fetch).not.toHaveBeenCalled();
    expect(JSON.stringify(state.feed)).toBe(before);
    expect(screen.queryByRole("button", { name: /trade|approve|collect|start|run/i })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });

  it.each(["http://127.0.0.1:5182/report.html", "http://localhost:5182/report.html", "http://[::1]:5182/report.html"])("links the separate configured local historical report %s", (url) => {
    render(<ShadowExperiment historicalReportUrl={url} />);
    expect(screen.getByRole("link", { name: "Open historical report" })).toHaveAttribute("href", url);
    expect(screen.queryByText(/6,165|0\.07262|0\.07352/)).not.toBeInTheDocument();
  });

  it.each(["", "https://example.com/report.html", "http://example.com/report.html", "javascript:alert(1)", "/report.html", "http://user:secret@127.0.0.1:5182/report.html", "https://127.0.0.1:5182/report.html"])("does not offer an unsafe or missing historical report URL %s", (url) => {
    render(<ShadowExperiment historicalReportUrl={url} />);
    expect(screen.queryByRole("link", { name: "Open historical report" })).not.toBeInTheDocument();
    expect(screen.getByText("Report link not configured.")).toBeInTheDocument();
  });

  it("uses the explicit local historical report environment setting", () => {
    vi.stubEnv("VITE_SHADOW_HISTORICAL_REPORT_URL", "http://127.0.0.1:5182/report.html"); render(<ShadowExperiment />);
    expect(screen.getByRole("link", { name: "Open historical report" })).toHaveAttribute("href", "http://127.0.0.1:5182/report.html");
  });

  it.each(["LOADING", "NOT_CONFIGURED", "UNAVAILABLE", "DISABLED"] as const)("shows %s with no substituted rows or graphics", (status) => {
    hook.mockReturnValue({ ...ready(), status, feed: null, message: "No saved records." }); render(<ShadowExperiment />);
    expect(screen.getByRole("status")).toBeInTheDocument(); expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "30-session progress" })).not.toBeInTheDocument();
  });

  it.each(["UNAVAILABLE", "DISABLED"] as const)("removes previous results when reading becomes %s", (status) => {
    hook.mockReturnValue(ready(true)); const { rerender } = render(<ShadowExperiment />);
    expect(screen.getByText("Candidate 1.00%")).toBeInTheDocument();
    hook.mockReturnValue({ ...ready(), status, feed: null, message: "Saved records are unavailable or reading is paused." });
    rerender(<ShadowExperiment />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByText("Candidate 1.00%")).not.toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /^Mean gross difference versus control/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "30-session progress" })).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
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
