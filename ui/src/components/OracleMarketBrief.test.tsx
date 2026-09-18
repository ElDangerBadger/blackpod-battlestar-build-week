import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MissionEvidenceName } from "../data/loadMission";
import { createMissionViewModel } from "../data/viewModel";
import { createMissionBundleFixture } from "../test/missionFixture";
import { createOracleMarketBriefFixture, oracleMarketBriefSourceDocuments } from "../test/oracleMarketBriefFixture";
import { OracleMarketNarrative } from "../books/OracleNarrative";
import { OracleMarketBrief } from "./OracleMarketBrief";

function fixture() {
  const brief = createOracleMarketBriefFixture(), bundle = createMissionBundleFixture();
  const documents = oracleMarketBriefSourceDocuments(brief);
  for (const [name, reference] of Object.entries(brief.evidence.source_artifacts)) {
    bundle.evidence = new Map(bundle.evidence).set(name as MissionEvidenceName, { name: name as MissionEvidenceName, reference, document: documents[name], status: "LOADED", message: null });
    bundle.artifactIndex = new Map(bundle.artifactIndex).set(name, reference);
  }
  const viewModel = createMissionViewModel(bundle); viewModel.oracleMarketBrief = brief;
  return { brief, viewModel };
}
const fetchSpy = vi.fn();
beforeEach(() => { fetchSpy.mockReset(); vi.stubGlobal("fetch", fetchSpy); });
afterEach(() => { expect(fetchSpy).not.toHaveBeenCalled(); vi.unstubAllGlobals(); });

describe("source-linked supplemental Oracle market brief", () => {
  it("shows the real report in six readable sections with source citations and distinct clocks", () => {
    const { brief, viewModel } = fixture(), original = JSON.stringify(brief);
    render(<OracleMarketBrief brief={brief} viewModel={viewModel} />);
    expect(screen.getByRole("heading", { name: "Oracle’s market brief" })).toBeVisible();
    expect(screen.getByText(brief.report.headline.text)).toBeVisible();
    for (const section of brief.report.sections) expect(screen.getByText(section.paragraphs[0].text)).toBeVisible();
    expect(screen.getByTitle(brief.evidence.as_of)).toHaveAttribute("dateTime", brief.evidence.as_of);
    expect(screen.getByTitle(brief.generated_at)).toHaveAttribute("dateTime", brief.generated_at);
    expect(screen.getByText(/does not verify that every interpretation/)).toBeVisible();
    const citations = screen.getAllByRole("link", { name: "Positive participation" });
    expect(citations[0]).toHaveAttribute("href", expect.stringContaining("oracle/oracle_measurements.json"));
    expect(citations[0]).toHaveAttribute("rel", "noreferrer");
    expect(JSON.stringify(brief)).toBe(original);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("discloses exact source values, model provenance, and missing revision honestly", () => {
    const { brief, viewModel } = fixture(); render(<OracleMarketBrief brief={brief} viewModel={viewModel} />);
    fireEvent.click(screen.getByText("Evidence behind this brief · 5 recorded facts"));
    expect(screen.getByLabelText("Recorded value: Positive participation")).toHaveTextContent("0.25");
    expect(screen.getByText(brief.evidence.facts[0].meaning)).toBeVisible();
    fireEvent.click(screen.getByText("Model provenance and limits"));
    expect(screen.getByText("synthetic-ui-model")).toBeVisible();
    expect(screen.getByText("Not recorded")).toBeVisible();
    expect(screen.getByText(/does not call the model/)).toBeVisible();
    expect(screen.getByText(brief.provenance.response_sha256)).toBeVisible();
  });

  it.each(["missing", "hash", "producer", "status", "unsafe path"])("does not link %s source evidence", (mode) => {
    const { brief, viewModel } = fixture(), name = "oracle_measurements";
    if (mode === "missing") viewModel.artifactIndex = new Map();
    if (mode === "hash" || mode === "producer") viewModel.artifactIndex = new Map(viewModel.artifactIndex).set(name, { ...brief.evidence.source_artifacts[name], [mode === "hash" ? "sha256" : "producer"]: "different" });
    if (mode === "status") viewModel.evidence = new Map(viewModel.evidence).set(name, { ...viewModel.evidence.get(name)!, status: "UNAVAILABLE" });
    if (mode === "unsafe path") brief.evidence.source_artifacts[name].path = "oracle/%2e%2e/secret.json";
    render(<OracleMarketBrief brief={brief} viewModel={viewModel} />);
    expect(screen.queryByRole("link", { name: "Positive participation" })).not.toBeInTheDocument();
    expect(screen.getAllByText("Positive participation · source link unavailable").length).toBeGreaterThan(0);
  });

  it("renders prose and exact values as text, never executable markup or markdown", () => {
    const { brief, viewModel } = fixture();
    brief.report.headline.text = "<img src=x onerror=alert(1)>";
    brief.report.sections[0].paragraphs[0].text = "[unsafe link](javascript:alert(1))";
    brief.evidence.facts[0].value = "<script>unsafe()</script>";
    const { container } = render(<OracleMarketBrief brief={brief} viewModel={viewModel} />);
    expect(screen.getByText(brief.report.headline.text)).toBeVisible();
    expect(container.querySelector("script,img")).toBeNull();
    expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
  });

  it("shows canonical warnings and blockers without claiming readiness grants authority", () => {
    const { brief, viewModel } = fixture(); brief.evidence.blockers = ["RECORDED_BLOCKER"];
    render(<OracleMarketBrief brief={brief} viewModel={viewModel} />);
    const limits = within(screen.getByRole("complementary", { name: "Canonical brief warnings and blockers" }));
    expect(limits.getByText("RECORDED_BLOCKER")).toBeVisible();
    expect(limits.getByText("MISSING_PRIOR_ORACLE_MEASUREMENTS")).toBeVisible();
  });

  it("places the optional brief before native prose without replacing old mission behavior", () => {
    const { brief, viewModel } = fixture();
    const { container, rerender } = render(<OracleMarketNarrative viewModel={viewModel} />);
    const text = container.textContent!;
    expect(text.indexOf(brief.report.headline.text)).toBeLessThan(text.indexOf("Oracle market narrative"));
    viewModel.oracleMarketBrief = null;
    rerender(<OracleMarketNarrative viewModel={viewModel} />);
    expect(screen.queryByRole("heading", { name: "Oracle’s market brief" })).not.toBeInTheDocument();
    expect(screen.getByText(/No verified longer-form ModelDock market brief/)).toBeVisible();
    expect(screen.getByRole("heading", { name: "Oracle market narrative" })).toBeVisible();
  });
});
