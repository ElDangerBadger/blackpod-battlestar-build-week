import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createSentryScanFixture } from "../test/sentryScanFixture";
import { useSentryScanFeed, type SentryScanState } from "../data/useSentryScanFeed";
import { SentryScanLedger } from "./SentryScanLedger";

vi.mock("../data/useSentryScanFeed", () => ({ useSentryScanFeed: vi.fn() }));
const hook = vi.mocked(useSentryScanFeed);
function ready(): SentryScanState { return { status: "READY", feed: createSentryScanFixture(), message: "", refreshing: false, refresh: vi.fn() }; }
function show(state = ready()) { hook.mockReturnValue(state); return render(<SentryScanLedger enabled />); }
beforeEach(() => vi.clearAllMocks());

describe("recorded Scan results presentation", () => {
  it("keeps recorded scans separate from live detections and frozen V2 evidence", () => {
    show();
    expect(screen.getByRole("heading", { name: "Recorded scan results—not live detections" })).toBeInTheDocument();
    expect(screen.getByText(/not the frozen V2 development comparison, a prospective success/)).toBeInTheDocument();
    expect(screen.getByText(/General equity & ETF · RESEARCH_ONLY/)).toBeInTheDocument();
    expect(screen.getByText(/06:00:00 UTC/)).toBeInTheDocument();
    expect(screen.getByText(/07:00:00 UTC/)).toBeInTheDocument();
    expect(screen.getByText(/A recent reader check does not make this scan/)).toBeInTheDocument();
  });
  it("retains both windows, supplied selections and five empty slots without padding", () => {
    show();
    const first = screen.getByRole("table", { name: "Selected candidates · 20-session baseline · supplied order" });
    const second = screen.getByRole("table", { name: "Selected candidates · 60-session baseline · supplied order" });
    expect(within(first).getByRole("rowheader")).toHaveTextContent("AAPL");
    expect(within(second).getByRole("rowheader")).toHaveTextContent("SPY");
    expect(within(first).getByText("98%")).toBeInTheDocument();
    expect(screen.getAllByText("5 unfilled slots · no padding")).toHaveLength(2);
    expect(screen.getByText(/not a probability of a price move/)).toBeInTheDocument();
  });
  it("separates excluded inputs from observed-but-not-selected candidates with evidence", () => {
    show();
    expect(screen.getByRole("heading", { name: "Failed / excluded inputs · 1" })).toBeInTheDocument();
    expect(screen.getByText("IWM · Excluded before selection · ETF")).toBeInTheDocument();
    expect(screen.getByText("SOURCE_CAPTURE_FAILED")).toBeInTheDocument();
    expect(screen.getByText("IWM-failure.json")).toBeInTheDocument();
    expect(screen.getByText("CONFLICT")).toBeInTheDocument();
    expect(screen.getByText("Observed but not selected · 1 · 20-session baseline")).toBeInTheDocument();
    expect(screen.getAllByText("NO_ELIGIBLE_ASSESSMENT").length).toBeGreaterThan(0);
    expect(within(screen.getByRole("list", { name: "Scan requested population", hidden: true })).getAllByRole("listitem", { hidden: true })).toHaveLength(3);
  });
  it("does not imply underlying evidence authenticity from reader integrity checks", () => {
    show();
    expect(screen.getByText(/not independent authenticity or the underlying history/)).toBeInTheDocument();
    expect(screen.getByText(/Declared evidence has not been reverified/)).toBeInTheDocument();
    expect(screen.getByText("scan.json")).toBeInTheDocument();
    expect(screen.getByText("references-test")).toBeInTheDocument();
    expect(screen.getByText("protocol-test")).toBeInTheDocument();
  });
  it("shows empty selections rather than inventing candidates", () => {
    const state = ready();
    state.feed!.scan!.windows.forEach((window) => { window.excluded.push(...window.selected); window.selected = []; window.capacity_remaining = 6; });
    show(state);
    expect(screen.getAllByText("No candidates selected for this window.")).toHaveLength(2);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getAllByText("6 unfilled slots · no padding")).toHaveLength(2);
  });
  it("provides only receipt refresh with no downstream actions", () => {
    const state = ready(); show(state);
    expect(screen.getAllByRole("button")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Refresh scan records" }));
    expect(state.refresh).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: /Run|Start|Navigator|watchlist|trade/i })).not.toBeInTheDocument();
    expect(screen.getByText(/does not run a scan, call a market-data provider/)).toBeInTheDocument();
  });
  it.each(["UNAVAILABLE", "NOT_CONFIGURED"] as const)("labels retained evidence explicitly stale under %s", (status) => {
    show({ ...ready(), status, message: "Reader unavailable." });
    expect(screen.getByRole("status")).toHaveTextContent("It has not been refreshed; current availability is unconfirmed");
    expect(screen.getByRole("table", { name: /20-session/ })).toBeInTheDocument();
  });
  it.each(["LOADING", "UNAVAILABLE", "NOT_CONFIGURED", "DISABLED"] as const)("does not fabricate evidence for %s", (status) => {
    show({ ...ready(), status, feed: null });
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText(/Missing evidence is not an all-clear/)).toBeInTheDocument();
  });
  it("disables reads during replay and in flight", () => {
    hook.mockReturnValue(ready()); const view = render(<SentryScanLedger enabled={false} />);
    expect(hook).toHaveBeenLastCalledWith({ enabled: false });
    expect(screen.getByRole("button")).toBeDisabled();
    hook.mockReturnValue({ ...ready(), refreshing: true }); view.rerender(<SentryScanLedger enabled />);
    expect(screen.getByRole("button")).toBeDisabled();
  });
});
