import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { createMissionViewModel, type CaptainLogEntryViewModel, type MissionViewModel } from "../data/viewModel";
import { artifact, createMissionBundleFixture } from "../test/missionFixture";
import { CaptainsLogDetails } from "./CaptainsLogDetails";

function mission(): MissionViewModel {
  const value = createMissionViewModel(createMissionBundleFixture());
  value.status.navigatorPlanStatus = null;
  value.status.operatorResult = null;
  value.status.outcome = "HELD";
  value.status.governorDisposition = "BLOCKED";
  value.stages.council.nativeState = "BLOCKED";
  value.captainsLog = [
    { stage: "COUNCIL", timestamp: "2026-09-15T22:02:03.123456Z", status: "SUCCEEDED", summary: "Council technically succeeded with native state BLOCKED.\nNo new action is implied.", evidenceCount: 4, sourceArtifacts: [] },
    { stage: "GOVERNOR", timestamp: "2026-09-15T22:03:04Z", status: "SUCCEEDED", summary: "Governor returned BLOCKED.", evidenceCount: 1, sourceArtifacts: [] },
    { stage: "OPERATOR", timestamp: "2026-09-15T22:04:05Z", status: "CLOSED_BLOCKED", summary: "Operator routing is CLOSED_BLOCKED; no action is implied.", evidenceCount: 2, sourceArtifacts: [] },
    { stage: "NAVIGATOR", timestamp: "2026-09-15T22:05:06Z", status: "NOT_STARTED", summary: "Navigator has not started.", evidenceCount: 1, sourceArtifacts: [] },
    { stage: "MISSION", timestamp: "2026-09-15T22:06:07Z", status: "HELD", summary: "Canonical mission outcome is HELD.", evidenceCount: 1, sourceArtifacts: [] },
  ];
  return value;
}

describe("Captain's Log expanded recorded details", () => {
  it("retains captured order with human-readable stage names, full timestamps, and evidence counts", () => {
    const value = mission();
    const before = structuredClone(value.captainsLog);
    const { container } = render(<CaptainsLogDetails mission={value} />);

    expect(screen.getAllByRole("article").map((article) => within(article).getByRole("heading").textContent)).toEqual([
      "Council · combined review", "Governor · decision gate", "Operator · recorded action",
      "Navigator · SHADOW planning", "Mission · recorded outcome",
    ]);
    const times = [...container.querySelectorAll("time")];
    expect(times[0]).toHaveTextContent("Sep 15, 2026, 10:02:03 PM UTC");
    expect(times.every((time) => time.textContent?.endsWith(" UTC"))).toBe(true);
    expect(times.map((time) => time.getAttribute("datetime"))).toEqual(value.captainsLog.map((entry) => entry.timestamp));
    expect(times.map((time) => time.getAttribute("title"))).toEqual(value.captainsLog.map((entry) => entry.timestamp));
    expect(within(screen.getByRole("article", { name: "Council · combined review" })).getByText("4 records")).toBeInTheDocument();
    expect(within(screen.getByRole("article", { name: "Governor · decision gate" })).getByText("1 record")).toBeInTheDocument();
    expect(value.captainsLog).toEqual(before);
  });

  it("distinguishes process completion, blocked decisions, and operator authority", () => {
    render(<CaptainsLogDetails mission={mission()} />);
    const council = within(screen.getByRole("article", { name: "Council · combined review" }));
    const governor = within(screen.getByRole("article", { name: "Governor · decision gate" }));
    const operator = within(screen.getByRole("article", { name: "Operator · recorded action" }));

    expect(council.getByText(/processing result, not action approval/)).toBeInTheDocument();
    expect(council.getByText(/completed review can still record a blocked result/)).toBeInTheDocument();
    expect(council.getByText(/Current recorded Council result: BLOCKED/)).toBeInTheDocument();
    expect(governor.getByText(/Even PROCEED is not operator approval/)).toBeInTheDocument();
    expect(governor.getByText(/Current recorded Governor disposition: BLOCKED/)).toBeInTheDocument();
    expect(operator.getByText(/route is closed because action is blocked/)).toBeInTheDocument();
    expect(screen.getByText(/no order or trade is executed/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("does not call an unstarted Navigator or absent plan a software failure", () => {
    render(<CaptainsLogDetails mission={mission()} />);
    const navigator = within(screen.getByRole("article", { name: "Navigator · SHADOW planning" }));

    expect(navigator.getByText(/not started.*not the same as a failed process/)).toBeInTheDocument();
    expect(navigator.getByText(/absence alone is not a software failure/)).toBeInTheDocument();
    expect(navigator.getByText(/separate market-reference chart/)).toBeInTheDocument();
  });

  it("keeps exact recorded summaries behind initially closed disclosures", () => {
    const value = mission();
    const { container } = render(<CaptainsLogDetails mission={value} />);
    const disclosures = [...container.querySelectorAll<HTMLDetailsElement>("details")];

    expect(disclosures).toHaveLength(value.captainsLog.length);
    disclosures.forEach((disclosure, index) => {
      expect(disclosure).not.toHaveAttribute("open");
      expect(disclosure.querySelector("summary")).toHaveTextContent("Recorded summary · exact wording");
      expect(disclosure.querySelector("p")!.textContent).toBe(value.captainsLog[index].summary);
    });
    fireEvent.click(disclosures[0].querySelector("summary")!);
    expect(disclosures[0]).toHaveAttribute("open");
  });

  it("retains unknown stage and status text without inventing an interpretation", () => {
    const value = mission();
    value.captainsLog = [
      { ...value.captainsLog[0], stage: "constructor" as CaptainLogEntryViewModel["stage"], status: "SUCCEEDED", summary: "Unknown component wording." },
      { ...value.captainsLog[1], status: "FUTURE_STATUS", summary: "Unknown status wording." },
    ];
    render(<CaptainsLogDetails mission={value} />);
    const unknownStage = within(screen.getByRole("article", { name: "constructor" }));
    const unknownStatus = within(screen.getByRole("article", { name: "Governor · decision gate" }));

    expect(unknownStage.getByText(/No plain-language interpretation is defined for this stage/)).toBeInTheDocument();
    expect(unknownStage.queryByText(/process completed successfully/)).toBeNull();
    expect(unknownStatus.getByText(/No plain-language interpretation is defined for this status/)).toBeInTheDocument();
    expect(unknownStatus.getByText("FUTURE_STATUS", { selector: "code" })).toBeInTheDocument();
    expect(unknownStage.getByText("Unknown component wording.")).toBeInTheDocument();
  });

  it("uses the recorded plan status without asserting execution and handles an empty log", () => {
    const value = mission();
    value.status.navigatorPlanStatus = "CREATED";
    const { rerender } = render(<CaptainsLogDetails mission={value} />);
    expect(screen.getByText(/Current recorded SHADOW plan status: CREATED.*not an executed order/)).toBeInTheDocument();
    rerender(<CaptainsLogDetails mission={{ ...value, captainsLog: [] }} />);
    expect(screen.getByText(/No Captain’s Log entries are recorded/)).toBeInTheDocument();
    expect(screen.queryByRole("article")).toBeNull();
  });

  it("formats an offset timestamp in UTC without changing the original instant or exact text", () => {
    const value = mission();
    const timestamp = "2026-09-15T23:30:40.123456-07:00";
    value.captainsLog = [{ ...value.captainsLog[0], timestamp }];
    const { container } = render(<CaptainsLogDetails mission={value} />);
    const time = container.querySelector("time")!;

    expect(time).toHaveTextContent("Sep 16, 2026, 6:30:40 AM UTC");
    expect(time).toHaveAttribute("datetime", timestamp);
    expect(time).toHaveAttribute("title", timestamp);
    expect(within(container.querySelector("details")!).getByText(timestamp, { selector: "code" })).toBeInTheDocument();
    expect(value.captainsLog[0].timestamp).toBe(timestamp);
  });

  it("links only the entry's recorded source artifacts under the supplied immutable mission base", () => {
    const value = mission();
    value.baseUrl = "/live/revisions/verified-capture/";
    const reference = artifact("council_synthesis", "council/outputs/council synthesis.json");
    value.captainsLog = [{ ...value.captainsLog[0], sourceArtifacts: [reference, reference] }];
    const { container } = render(<CaptainsLogDetails mission={value} />);
    const disclosure = container.querySelector("details")!;
    expect(disclosure).not.toHaveAttribute("open");
    expect(screen.getByRole("link").closest("details")).toBe(disclosure);
    fireEvent.click(disclosure.querySelector("summary")!);
    const links = within(disclosure).getAllByRole("link");

    expect(links).toHaveLength(1);
    expect(links[0]).toHaveTextContent(reference.path);
    expect(links[0]).toHaveAttribute("href", "/live/revisions/verified-capture/council/outputs/council%20synthesis.json");
    expect(links[0]).toHaveAttribute("target", "_blank");
    expect(links[0]).toHaveAttribute("rel", "noreferrer");
    expect(container.querySelectorAll("a")).toHaveLength(1);
    expect(screen.getByText("4 records")).toBeInTheDocument();
  });

  it("rejects unsafe paths without guessing substitutes or changing the evidence count", () => {
    const value = mission();
    const unsafe = ["../private.json", "/private.json", "a/../private.json", "a//b.json", "a\\b.json", "https://example.com/data", "javascript:alert(1)", "%2e%2e/secret", "file.json?token=x", "file.json#part", "a\n.json"];
    value.captainsLog = [{ ...value.captainsLog[0], sourceArtifacts: unsafe.map((path) => artifact("unsafe", path)) }];
    const { container } = render(<CaptainsLogDetails mission={value} />);
    fireEvent.click(container.querySelector("summary")!);

    expect(container.querySelectorAll("a")).toHaveLength(0);
    expect(screen.getByText("Unsafe recorded artifact paths were not linked.")).toBeInTheDocument();
    expect(screen.getByText("No safe artifact links are available for this entry.")).toBeInTheDocument();
    expect(screen.getByText("4 records")).toBeInTheDocument();
  });
});
