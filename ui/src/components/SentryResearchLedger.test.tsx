import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createSentryResearchFixture } from "../test/sentryResearchFixture";
import { useSentryResearchFeed, type SentryResearchState } from "../data/useSentryResearchFeed";
import { SentryResearchLedger } from "./SentryResearchLedger";

vi.mock("../data/useSentryResearchFeed", () => ({ useSentryResearchFeed: vi.fn() }));
const hook = vi.mocked(useSentryResearchFeed);
function ready(): SentryResearchState { return { status: "READY", feed: createSentryResearchFixture(), message: "", refreshing: false, refresh: vi.fn() }; }
function show(state = ready()) { hook.mockReturnValue(state); return render(<SentryResearchLedger enabled />); }
beforeEach(() => { vi.clearAllMocks(); });

describe("Sentry Research presentation", () => {
  it("distinguishes genuine historical development from synthetic archives and independent evidence", () => {
    show();
    expect(screen.getByRole("heading", { name: "Historical research, not live detections" })).toBeInTheDocument();
    expect(screen.getByText(/Recorded historical market-data research, separate from Microcap observations/)).toBeInTheDocument();
    expect(screen.getByText(/development sessions already seen by V1—not an independent holdout/)).toBeInTheDocument();
    expect(screen.getByText("2019–2022")).toBeInTheDocument();
    expect(screen.getByText(/A newer reader check does not make/)).toBeInTheDocument();
    expect(screen.getByText(/04:40:00 UTC/)).toBeInTheDocument();
    expect(screen.getByText(/05:00:00 UTC/)).toBeInTheDocument();
  });
  it("shows all supplied policy/window outcomes and capped-by-construction caveat without a winner", () => {
    show();
    const table = screen.getByRole("table", { name: "Supplied workload results · both windows retained" });
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    expect(within(table).getByText("3.3247")).toBeInTheDocument();
    expect(within(table).getByText("53.64%")).toBeInTheDocument();
    expect(within(table).getByText("New names: met by construction")).toBeInTheDocument();
    expect(within(table).getAllByText("Overlap: not met")).toHaveLength(3);
    expect(screen.getByText(/No policy meets both workload criteria/)).toBeInTheDocument();
    expect(screen.getByText(/Its lower churn is not independent proof/)).toBeInTheDocument();
  });
  it("shows supplied contributors as historical frequencies and all56 cohort members", () => {
    show();
    expect(screen.getAllByRole("table", { name: /Supplied top 6 historical contributors/, hidden: true })).toHaveLength(6);
    const cohort = screen.getByRole("list", { name: "Full research cohort", hidden: true });
    expect(within(cohort).getAllByRole("listitem", { hidden: true })).toHaveLength(56);
    expect(within(cohort).getByText("IWM")).toBeInTheDocument();
    expect(screen.getByText(/neither current signals nor investment rankings/)).toBeInTheDocument();
  });
  it("keeps the failed warmup and0/60 distinct from sealed failure evidence", () => {
    show();
    expect(screen.getByText("Blocked · 0 / 60 complete")).toBeInTheDocument();
    expect(screen.getByText("Warmup failed · the full cohort was not sealed")).toBeInTheDocument();
    expect(screen.getByText(/23 symbol captures ready · 1 failed · 32 blocked/)).toBeInTheDocument();
    expect(screen.getByText(/That preserves the failure; it does not mean the warmup succeeded/)).toBeInTheDocument();
    expect(screen.getByText(/had a recorded volume conflict/)).toHaveTextContent("IWM");
    expect(screen.getByText("40,000,000")).toBeInTheDocument();
    expect(screen.getByText(/Neither vintage has been established here as correct/)).toBeInTheDocument();
    expect(screen.getByText(/current state not checked/)).toBeInTheDocument();
    expect(screen.getByText(/Official Cboe early-close timing remains unresolved/)).toBeInTheDocument();
  });
  it("exposes only refresh, never watchlist/navigation/collector execution actions", () => {
    const state = ready(); show(state);
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: /Navigator|watchlist|Start|Run|trade/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh research records" }));
    expect(state.refresh).toHaveBeenCalledOnce();
    expect(screen.getByText(/does not start the collector, acquire market data, run a model/)).toBeInTheDocument();
  });
  it("labels last-good results as unrefreshed after a failed or unconfigured read", () => {
    show({ ...ready(), status: "UNAVAILABLE", message: "Read unavailable." });
    expect(screen.getByRole("status")).toHaveTextContent("current availability is unconfirmed");
    expect(screen.getByText("Read unavailable.")).toBeInTheDocument();
    expect(screen.getByText("Blocked · 0 / 60 complete")).toBeInTheDocument();
  });
  it.each(["LOADING", "NOT_CONFIGURED", "UNAVAILABLE", "DISABLED"] as const)("renders %s without invented results", (status) => {
    show({ ...ready(), status, feed: null, message: "No record loaded." });
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText(/Missing evidence is not an all-clear/)).toBeInTheDocument();
  });
  it("disables refresh when replayed or busy and uses the hook enabled boundary", () => {
    hook.mockReturnValue({ ...ready(), refreshing: true });
    const view = render(<SentryResearchLedger enabled />);
    expect(screen.getByRole("button")).toBeDisabled();
    hook.mockReturnValue(ready()); view.rerender(<SentryResearchLedger enabled={false} />);
    expect(hook).toHaveBeenLastCalledWith({ enabled: false });
    expect(screen.getByRole("button")).toBeDisabled();
  });
});
