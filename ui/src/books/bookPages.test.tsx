import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { createMissionViewModel } from "../data/viewModel";
import { createMissionBundleFixture } from "../test/missionFixture";
import { buildBookDefinitions } from "./bookPages";

describe("focused stage books", () => {
  it("provides every requested book and page count", () => {
    const definitions = buildBookDefinitions(createMissionViewModel(createMissionBundleFixture()));
    expect(definitions.map((book) => [book.id, book.pages.length])).toEqual([
      ["harbormaster", 4],
      ["oracle", 6],
      ["council", 4],
      ["governor", 4],
      ["navigator", 6],
    ]);
  });

  it("states that Governor PROCEED is not mission approval", () => {
    const definitions = buildBookDefinitions(createMissionViewModel(createMissionBundleFixture()));
    const governor = definitions.find((book) => book.id === "governor");
    render(<>{governor?.pages[0]?.content}</>);

    expect(screen.getByText(/Governor PROCEED is not mission approval/)).toBeInTheDocument();
  });

  it("keeps SHADOW-only allowed and prohibited operations visible", () => {
    const definitions = buildBookDefinitions(createMissionViewModel(createMissionBundleFixture()));
    const navigator = definitions.find((book) => book.id === "navigator");
    render(<>{navigator?.pages[3]?.content}{navigator?.pages[4]?.content}</>);

    expect(screen.getByText(/Navigator SHADOW handoff only/)).toBeInTheDocument();
    expect(screen.getByText("PLAN_ONLY")).toBeInTheDocument();
    expect(screen.getByText("SUBMIT_ORDER")).toBeInTheDocument();
    expect(screen.getByText("BROKER_CALL")).toBeInTheDocument();
  });

  it("handles absent optional evidence without inventing data", () => {
    const definitions = buildBookDefinitions(createMissionViewModel(createMissionBundleFixture()));
    const oracle = definitions.find((book) => book.id === "oracle");
    render(<>{oracle?.pages[1]?.content}</>);

    expect(screen.getAllByText("Not present in this mission artifact.").length).toBeGreaterThan(0);
    expect(screen.getByText(/not security-specific trade signals/)).toBeInTheDocument();
  });
});

