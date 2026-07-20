import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createMissionBundleFixture } from "./test/missionFixture";

vi.mock("./data/loadMission", async (importOriginal) => {
  const original = await importOriginal<typeof import("./data/loadMission")>();
  return {
    ...original,
    loadMissionBundle: vi.fn(async () => createMissionBundleFixture()),
  };
});

import App from "./App";

describe("Captain's Cabin", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows the canonical approval chain and SHADOW-only boundary", async () => {
    render(<App />);

    expect(await screen.findByText("APPROVED · COMPLETE")).toBeInTheDocument();
    expect(screen.getAllByText("NAVIGATOR_SHADOW_HANDOFF").length).toBeGreaterThan(0);
    expect(screen.getByText("APPROVED_FOR_HANDOFF")).toBeInTheDocument();
    expect(screen.getAllByText(/PROCEED is not approval/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Navigator SHADOW handoff only/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Oracle remains authoritative for facts/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Mission Brief", hidden: true })).toHaveAttribute(
      "href",
      "/demo/approved/presentation/mission_brief.html",
    );
    expect(screen.getByText("Rotate device")).toBeInTheDocument();
  });

  it("opens a stage book with keyboard-safe page navigation and returns to the desk", async () => {
    render(<App />);
    const oracleButton = await screen.findByRole("button", { name: "Open Oracle book" });

    fireEvent.click(oracleButton);
    expect(screen.getByRole("dialog", { name: "Oracle" })).toBeInTheDocument();
    expect(screen.getByText("Page 1 of 6")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Page 2 of 6")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Oracle" })).not.toBeInTheDocument());
  });

  it("restarts the presentation without changing the canonical outcome", async () => {
    render(<App />);
    expect(await screen.findByText("APPROVED · COMPLETE")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Restart" }));

    expect(screen.getByText("APPROVED · COMPLETE")).toBeInTheDocument();
    expect(screen.getByText("Ready to replay")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open Oracle book" })).not.toBeInTheDocument();
    expect(screen.getByText(/Navigator SHADOW handoff only/i)).toBeInTheDocument();
  });
});
