import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { JsonObject } from "../contracts/presentation";
import type { MissionBundle, MissionEvidenceName } from "../data/loadMission";
import { createMissionViewModel } from "../data/viewModel";
import { artifact, createMissionBundleFixture } from "../test/missionFixture";
import { buildBookDefinitions } from "./bookPages";
import { ModelDockNarrativeDetails, OracleMarketNarrative } from "./OracleNarrative";

const WHEN = "2026-09-15T23:05:20Z";
const PROSE = {
  summary: "Oracle structure: CONTRACTING_BREADTH, MIXED_LEADERSHIP, MIXED_ROTATION, NEUTRAL.",
  breadth_commentary: "Market participation is contracting.",
  leadership_commentary: "Leadership is neither broadly distributed nor tightly concentrated.",
  rotation_commentary: "Sector rotation is mixed between defensive and cyclical groups.",
  risk_regime_commentary: "The current structure reflects a balanced risk posture.",
};
const fetchSpy = vi.fn();

function attach(bundle: MissionBundle, name: MissionEvidenceName, document: JsonObject) {
  const reference = { ...artifact(name, `oracle/${name}.json`), producer: name.startsWith("oracle_modeldock") ? "modeldock" : "oracle" };
  bundle.evidence = new Map(bundle.evidence).set(name, { name, document, reference, status: "LOADED", message: null });
  bundle.artifactIndex = new Map(bundle.artifactIndex).set(name, reference);
}

function fixture() {
  const bundle = createMissionBundleFixture();
  const native: JsonObject = {
    ...PROSE, narrative_id: "native-narrative-001", assessment_id: "assessment-001",
    as_of: WHEN, generated_at: WHEN, warnings: [], blockers: [], dashboard_ready: true,
  };
  const report: JsonObject = {
    report_id: "report-001", narrative_id: "native-narrative-001", assessment_id: "assessment-001",
    headline: "Contracting breadth with neutral structure.", summary: "Saved report summary, not replacement commentary.",
    as_of: WHEN, generated_at: WHEN, narrative_summary: { ...PROSE },
    warnings: ["EXCLUDED_ORACLE_SNAPSHOT_SYMBOLS:VXZ,IWF,IWD,IWM,MTUM,USMV,QUAL", "MISSING_PRIOR_ORACLE_MEASUREMENTS"],
    blockers: [],
  };
  const model: JsonObject = {
    schema_version: "blackpod.oracle_narrative.v1", mission_id: bundle.summary.mission_id,
    request_id: bundle.summary.request_id, symbol: "AAPL",
    summary: "Validated Oracle facts reflect contracting breadth, mixed leadership, and mixed rotation.",
    interpretation: "The source-linked facts suggest a current state of readiness and completeness.",
    confidence_explanation: "Confidence is bounded by the source-linked facts.",
    observed_facts: [
      { source_artifact: "oracle_assessment", json_pointer: "/breadth_posture", value: "CONTRACTING_BREADTH", statement: "The source-linked breadth posture is CONTRACTING_BREADTH." },
      { source_artifact: "oracle_assessment", json_pointer: "/leadership_posture", value: "MIXED_LEADERSHIP", statement: "The source-linked leadership posture is MIXED_LEADERSHIP." },
      { source_artifact: "oracle_assessment", json_pointer: "/rotation_posture", value: "MIXED_ROTATION", statement: "The source-linked rotation posture is MIXED_ROTATION." },
      { source_artifact: "oracle_measurement_diagnostics", json_pointer: "/diagnostics_state", value: "READY", statement: "The source-linked diagnostics state is READY." },
      { source_artifact: "oracle_readiness_report", json_pointer: "/readiness_state", value: "READY", statement: "The source-linked readiness state is READY." },
    ],
    uncertainties: [], warnings: [...report.warnings as string[]], prohibited_actions_acknowledged: true,
  };
  attach(bundle, "oracle_report", report);
  attach(bundle, "oracle_narrative", native);
  attach(bundle, "oracle_modeldock_narrative", model);
  attach(bundle, "oracle_assessment", { assessment_id: "assessment-001", breadth_posture: "CONTRACTING_BREADTH", leadership_posture: "MIXED_LEADERSHIP", rotation_posture: "MIXED_ROTATION", risk_regime_posture: "NEUTRAL", confidence: 1 });
  attach(bundle, "oracle_measurement_diagnostics", { diagnostics_state: "READY" });
  attach(bundle, "oracle_readiness_report", { readiness_state: "READY" });
  return { bundle, native, report, model };
}

function without(bundle: MissionBundle, name: MissionEvidenceName) {
  const evidence = new Map(bundle.evidence);
  evidence.delete(name);
  bundle.evidence = evidence;
}

beforeEach(() => {
  fetchSpy.mockReset();
  vi.stubGlobal("fetch", fetchSpy);
});

afterEach(() => {
  expect(fetchSpy).not.toHaveBeenCalled();
  vi.unstubAllGlobals();
});

describe("visible native Oracle narrative", () => {
  it("shows current-shaped report commentary, summary, timing and limitations without changing source documents", () => {
    const { bundle, native, report, model } = fixture();
    const before = JSON.stringify({ native, report, model });
    render(<OracleMarketNarrative viewModel={createMissionViewModel(bundle)} />);
    for (const prose of Object.values(PROSE)) expect(screen.getByText(prose)).toBeVisible();
    expect(screen.getByTitle(WHEN)).toBeVisible();
    expect(screen.getByTitle(WHEN)).toHaveAttribute("dateTime", WHEN);
    expect(screen.getByText(/No usable earlier measurement comparison/)).toBeVisible();
    expect(screen.getByText(/Excluded symbols: VXZ, IWF, IWD, IWM, MTUM, USMV, QUAL/)).toBeVisible();
    expect(screen.queryByText(model.summary as string)).not.toBeInTheDocument();
    expect(JSON.stringify({ native, report, model })).toBe(before);
  });

  it("keeps six pages and exposes native commentary and model facts outside closed exact-value disclosures", () => {
    const { bundle, model } = fixture();
    const book = buildBookDefinitions(createMissionViewModel(bundle)).find((entry) => entry.id === "oracle")!;
    expect(book.pages).toHaveLength(6);
    render(<>{book.pages[0].content}{book.pages[3].content}</>);
    expect(screen.getByText(PROSE.breadth_commentary)).toBeVisible();
    expect(screen.getByText(PROSE.breadth_commentary).closest("details")).toBeNull();
    const statement = (model.observed_facts as JsonObject[])[0].statement as string;
    expect(screen.getByText(statement)).toBeVisible();
    expect(screen.getByText(statement).closest("details")).toBeNull();
  });

  it("does not fill a partial report narrative with fields from another native artifact", () => {
    const { bundle, native, report } = fixture();
    report.narrative_summary = { summary: "Selected report narrative.", breadth_commentary: "Only the report breadth was supplied." };
    native.leadership_commentary = "Do not borrow this standalone leadership.";
    render(<OracleMarketNarrative viewModel={createMissionViewModel(bundle)} />);
    expect(screen.getByText("Selected report narrative.")).toBeVisible();
    expect(screen.getByText("Only the report breadth was supplied.")).toBeVisible();
    expect(screen.queryByText("Do not borrow this standalone leadership.")).not.toBeInTheDocument();
    expect(screen.queryByText(PROSE.rotation_commentary)).not.toBeInTheDocument();
    expect(screen.getAllByText("No commentary recorded for this topic in the selected source.")).toHaveLength(3);
  });

  it("retains correlated native-only warnings without mixing standalone prose into the selected report narrative", () => {
    const { bundle, native, report } = fixture();
    native.breadth_commentary = "Standalone prose must not replace report prose.";
    native.warnings = ["MISSING_PRIOR_ORACLE_MEASUREMENTS", "Additional correlated native limitation."];
    render(<OracleMarketNarrative viewModel={createMissionViewModel(bundle)} />);
    expect(screen.getByText(PROSE.breadth_commentary)).toBeVisible();
    expect(screen.queryByText(native.breadth_commentary as string)).not.toBeInTheDocument();
    const limitations = within(screen.getByRole("complementary", { name: "Recorded narrative limitations" }));
    expect(limitations.getAllByRole("listitem")).toHaveLength((report.warnings as string[]).length + 1);
    expect(limitations.getByText("Additional correlated native limitation.", { exact: false })).toBeVisible();
    expect(limitations.getAllByText(/No usable earlier measurement comparison/)).toHaveLength(1);
  });

  it("does not mix a mismatched standalone narrative's warnings into selected report content", () => {
    const { bundle, native } = fixture();
    native.assessment_id = "another-assessment";
    native.warnings = ["Unrelated native limitation must stay separate."];
    render(<OracleMarketNarrative viewModel={createMissionViewModel(bundle)} />);
    expect(screen.getByText(PROSE.breadth_commentary)).toBeVisible();
    expect(screen.queryByText("Unrelated native limitation must stay separate.", { exact: false })).not.toBeInTheDocument();
    expect(screen.getByText(/No usable earlier measurement comparison/)).toBeVisible();
  });

  it("uses a correlated standalone native narrative when the composed report narrative is absent", () => {
    const { bundle, native, report } = fixture();
    delete report.narrative_summary;
    native.summary = "The correlated standalone narrative.";
    render(<OracleMarketNarrative viewModel={createMissionViewModel(bundle)} />);
    expect(screen.getByText("The correlated standalone narrative.")).toBeVisible();
    expect(screen.getByText(PROSE.rotation_commentary)).toBeVisible();
    expect(screen.queryByText(report.summary as string)).not.toBeInTheDocument();
  });

  it.each(["narrative_id", "assessment_id"])("rejects standalone fallback when the report's %s conflicts", (field) => {
    const { bundle, native, report } = fixture();
    delete report.narrative_summary;
    native[field] = "different-source";
    render(<OracleMarketNarrative viewModel={createMissionViewModel(bundle)} />);
    expect(screen.getByText(report.summary as string)).toBeVisible();
    expect(screen.queryByText(PROSE.breadth_commentary)).not.toBeInTheDocument();
    expect(screen.getByText(/summary only/i)).toBeVisible();
  });

  it("shows report summary only when no usable native narrative is loaded", () => {
    const { bundle, report } = fixture();
    delete report.narrative_summary;
    without(bundle, "oracle_narrative");
    render(<OracleMarketNarrative viewModel={createMissionViewModel(bundle)} />);
    expect(screen.getByText(report.summary as string)).toBeVisible();
    expect(screen.getByText(/summary only/i)).toBeVisible();
    expect(screen.queryByText(PROSE.breadth_commentary)).not.toBeInTheDocument();
  });

  it("can read a standalone narrative when no report exists without inventing report details", () => {
    const { bundle } = fixture();
    without(bundle, "oracle_report");
    render(<OracleMarketNarrative viewModel={createMissionViewModel(bundle)} />);
    expect(screen.getByText(PROSE.summary)).toBeVisible();
    expect(screen.getByText(PROSE.leadership_commentary)).toBeVisible();
    expect(screen.queryByText(/MISSING_PRIOR_ORACLE_MEASUREMENTS/)).not.toBeInTheDocument();
  });

  it.each([null, [], "not an object", { breadth_commentary: 42, summary: ["not prose"] }])("does not render malformed native fields as fabricated prose: %j", (malformed) => {
    const { bundle, report } = fixture();
    report.narrative_summary = malformed;
    without(bundle, "oracle_narrative");
    const { container } = render(<OracleMarketNarrative viewModel={createMissionViewModel(bundle)} />);
    expect(container).not.toHaveTextContent("[object Object]");
    expect(screen.queryByText("not prose")).not.toBeInTheDocument();
    expect(screen.queryByText(PROSE.breadth_commentary)).not.toBeInTheDocument();
  });

  it("does not render cached document content marked UNAVAILABLE", () => {
    const { bundle } = fixture();
    const evidence = new Map(bundle.evidence);
    for (const name of ["oracle_report", "oracle_narrative"] as const) {
      evidence.set(name, { ...evidence.get(name)!, status: "UNAVAILABLE", message: "Source unavailable." });
    }
    bundle.evidence = evidence;
    render(<OracleMarketNarrative viewModel={createMissionViewModel(bundle)} />);
    expect(screen.queryByText(PROSE.summary)).not.toBeInTheDocument();
    expect(screen.queryByText(PROSE.breadth_commentary)).not.toBeInTheDocument();
    expect(screen.getByText(/No recorded Oracle market narrative is available/)).toBeVisible();
  });
});

describe("source-linked ModelDock narrative details", () => {
  it("shows all five facts and source pointers with confidence text and safe indexed evidence links", () => {
    const { bundle, model } = fixture();
    const before = JSON.stringify(model);
    render(<ModelDockNarrativeDetails viewModel={createMissionViewModel(bundle)} />);
    for (const fact of model.observed_facts as JsonObject[]) {
      expect(screen.getByText(fact.statement as string)).toBeVisible();
      expect(screen.getByText(fact.json_pointer as string)).toBeVisible();
    }
    expect(screen.getByText(model.confidence_explanation as string)).toBeVisible();
    expect(screen.getByText(/Recorded model: demo-model · Provider: mlx/)).toBeVisible();
    expect(screen.getByText(/does not start inference or check the model’s present availability/)).toBeVisible();
    expect(screen.getByText(/not a calibrated probability or proof of complete coverage/)).toBeVisible();
    const links = screen.getAllByRole("link");
    expect(links.length).toBeGreaterThanOrEqual(3);
    for (const link of links) {
      expect(link.getAttribute("href")).toMatch(/^\.\/demo\/approved\/oracle\/oracle_(assessment|measurement_diagnostics|readiness_report)\.json$/);
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveAttribute("rel", "noreferrer");
    }
    expect(JSON.stringify(model)).toBe(before);
  });

  it("labels an empty uncertainty list without promising certainty or complete data", () => {
    const { bundle } = fixture();
    render(<ModelDockNarrativeDetails viewModel={createMissionViewModel(bundle)} />);
    expect(screen.getByText(/No uncertainty items were recorded/)).toBeVisible();
    expect(screen.getByText(/not an assessment that uncertainty is absent/)).toBeVisible();
    expect(screen.queryByText(/^No uncertainty\.?$/i)).not.toBeInTheDocument();
  });

  it("renders supplied uncertainties and warnings as distinct literal list items", () => {
    const { bundle, model } = fixture();
    model.uncertainties = ["First recorded uncertainty.", "Second recorded uncertainty."];
    model.warnings = ["First recorded warning.", "Second recorded warning."];
    render(<ModelDockNarrativeDetails viewModel={createMissionViewModel(bundle)} />);
    for (const value of [...model.uncertainties as string[], ...model.warnings as string[]]) {
      expect(screen.getByText(value, { exact: false })).toBeVisible();
      expect(screen.getByText(value, { exact: false }).closest("li")).not.toBeNull();
    }
  });

  it.each(["../private.json", "https://untrusted.example/evidence.json", "oracle/%2e%2e/private.json", "oracle\\private.json"])("does not create a source link from unsafe indexed path %s", (path) => {
    const { bundle, model } = fixture();
    model.observed_facts = [(model.observed_facts as JsonObject[])[0]];
    const indexed = new Map(bundle.artifactIndex);
    indexed.set("oracle_assessment", { ...indexed.get("oracle_assessment")!, path });
    bundle.artifactIndex = indexed;
    bundle.evidence = new Map(bundle.evidence).set("oracle_assessment", {
      ...bundle.evidence.get("oracle_assessment")!, reference: indexed.get("oracle_assessment")!,
    });
    render(<ModelDockNarrativeDetails viewModel={createMissionViewModel(bundle)} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText("The source-linked breadth posture is CONTRACTING_BREADTH.")).toBeVisible();
  });

  it("confines a scheme-looking indexed filename to the encoded publication path", () => {
    const { bundle, model } = fixture();
    model.observed_facts = [(model.observed_facts as JsonObject[])[0]];
    const reference = { ...bundle.artifactIndex.get("oracle_assessment")!, path: "javascript:alert(1)" };
    bundle.artifactIndex = new Map(bundle.artifactIndex).set("oracle_assessment", reference);
    bundle.evidence = new Map(bundle.evidence).set("oracle_assessment", {
      ...bundle.evidence.get("oracle_assessment")!, reference,
    });
    render(<ModelDockNarrativeDetails viewModel={createMissionViewModel(bundle)} />);
    expect(screen.getByRole("link", { name: "oracle_assessment" })).toHaveAttribute("href", "./demo/approved/javascript%3Aalert(1)");
  });

  it.each(["UNAVAILABLE", "different-hash"])("does not link evidence whose availability/integrity is %s", (failure) => {
    const { bundle, model } = fixture();
    model.observed_facts = [(model.observed_facts as JsonObject[])[0]];
    if (failure === "UNAVAILABLE") {
      bundle.evidence = new Map(bundle.evidence).set("oracle_assessment", {
        ...bundle.evidence.get("oracle_assessment")!, status: "UNAVAILABLE", message: "Source could not be verified.",
      });
    } else {
      bundle.artifactIndex = new Map(bundle.artifactIndex).set("oracle_assessment", {
        ...bundle.artifactIndex.get("oracle_assessment")!, sha256: "b".repeat(64),
      });
    }
    render(<ModelDockNarrativeDetails viewModel={createMissionViewModel(bundle)} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText(/Source evidence not available for linking/)).toBeVisible();
  });

  it("does not guess a source link when a fact's artifact is not indexed", () => {
    const { bundle, model } = fixture();
    model.observed_facts = [(model.observed_facts as JsonObject[])[0]];
    bundle.artifactIndex = new Map();
    render(<ModelDockNarrativeDetails viewModel={createMissionViewModel(bundle)} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText("/breadth_posture")).toBeVisible();
  });

  it("renders unknown statement text literally without executing markup", () => {
    const { bundle, model } = fixture();
    model.observed_facts = [{ source_artifact: "unknown_artifact", json_pointer: "/unknown", value: "<script>bad()</script>", statement: "<img src=x onerror=alert(1)>" }];
    const { container } = render(<ModelDockNarrativeDetails viewModel={createMissionViewModel(bundle)} />);
    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeVisible();
    expect(container.querySelector("img, script")).toBeNull();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("preserves partial model evidence without converting malformed fields to facts or certainty", () => {
    const { bundle, model } = fixture();
    model.confidence_explanation = { unexpected: true };
    model.observed_facts = [null, { statement: ["not prose"], source_artifact: 42 }, { statement: "One recorded statement remains." }];
    model.uncertainties = "not an array";
    const { container } = render(<ModelDockNarrativeDetails viewModel={createMissionViewModel(bundle)} />);
    expect(screen.getByText("No confidence explanation was recorded.")).toBeVisible();
    expect(screen.getAllByText("This recorded statement is unavailable or has an unsupported format.")).toHaveLength(2);
    expect(screen.getByText("One recorded statement remains.")).toBeVisible();
    expect(screen.getByText("No uncertainty list was recorded.")).toBeVisible();
    expect(screen.queryByText(/No uncertainty items were recorded/)).not.toBeInTheDocument();
    expect(container).not.toHaveTextContent("[object Object]");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("deduplicates repeated warning codes while retaining distinct report and model limitations", () => {
    const { bundle, report, model } = fixture();
    report.warnings = ["Shared recorded warning.", "Report-only warning."];
    model.warnings = ["Shared recorded warning.", "Model-only warning."];
    render(<ModelDockNarrativeDetails viewModel={createMissionViewModel(bundle)} />);
    const limitations = within(screen.getByRole("complementary", { name: "Recorded narrative limitations" }));
    expect(limitations.getAllByRole("listitem")).toHaveLength(3);
    expect(limitations.getByText("Shared recorded warning.", { exact: false })).toBeVisible();
    expect(limitations.getByText("Report-only warning.", { exact: false })).toBeVisible();
    expect(limitations.getByText("Model-only warning.", { exact: false })).toBeVisible();
  });

  it("does not invent model facts or confidence when model output is absent", () => {
    const { bundle } = fixture();
    without(bundle, "oracle_modeldock_narrative");
    render(<ModelDockNarrativeDetails viewModel={createMissionViewModel(bundle)} />);
    expect(screen.queryByText("Confidence is bounded by the source-linked facts.")).not.toBeInTheDocument();
    expect(screen.queryByText(/The source-linked .* is/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText(/No recorded ModelDock narrative details are available/)).toBeVisible();
  });
});
