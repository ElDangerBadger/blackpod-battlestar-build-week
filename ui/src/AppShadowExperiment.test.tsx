import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./data/useLiveMission", () => ({ useLiveMission: vi.fn(), evidenceFreshness: vi.fn() }));
vi.mock("./data/useShadowExperiment", () => ({ useShadowExperiment: vi.fn() }));
import App from "./App";
import { useLiveMission } from "./data/useLiveMission";
import { useShadowExperiment } from "./data/useShadowExperiment";

describe("independent research view routing", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useShadowExperiment).mockReturnValue({ status: "NOT_CONFIGURED", feed: null, message: "No experiment configured.", refreshing: false, refresh: vi.fn() });
    vi.mocked(useLiveMission).mockReturnValue({ status: "NOT_CONFIGURED", mission: null, message: "No mission configured.", refreshing: false, refresh: vi.fn(), checkedAt: null, verifiedAt: null });
  });
  afterEach(() => { window.history.replaceState(null, "", "/"); });
  it("opens the explicit research page without reading a mission", () => {
    window.history.replaceState(null, "", "/?view=research"); render(<App />);
    expect(screen.getByRole("heading", { name: "One hypothesis. One frozen experiment." })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "No experiment configured" })).toBeInTheDocument();
    expect(useLiveMission).not.toHaveBeenCalled(); expect(useShadowExperiment).toHaveBeenCalledWith({ enabled: true });
  });
  it("offers the experiment view even when no mission is configured", () => {
    window.history.replaceState(null, "", "/"); render(<App />);
    expect(screen.getByRole("link", { name: "Open research experiment" })).toHaveAttribute("href", "/?view=research");
    expect(useShadowExperiment).not.toHaveBeenCalled();
  });
});
