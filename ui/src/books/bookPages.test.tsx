import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { JsonObject } from "../contracts/presentation";
import type { MissionBundle, MissionEvidenceName } from "../data/loadMission";
import { createMissionViewModel } from "../data/viewModel";
import { artifact, createMissionBundleFixture } from "../test/missionFixture";
import { buildBookDefinitions } from "./bookPages";
import { explainRecordedCode } from "./ledgerBriefings";
import { BookFocus } from "./BookFocus";

function withEvidence(bundle: MissionBundle, name: MissionEvidenceName, document: JsonObject): MissionBundle {
  const evidence = new Map(bundle.evidence);
  evidence.set(name, { name, document, reference: artifact(name, `evidence/${name}.json`), status: "LOADED", message: null });
  return { ...bundle, evidence };
}

function readOnlyMission() {
  // Relevant recorded fields from mission-live-aapl-20260915-002. Kept local so
  // this test does not depend on ignored captures or acquire market data.
  let bundle = createMissionBundleFixture();
  bundle.summary.stages.council = { technical_status: "SUCCEEDED", native_state: "BLOCKED" };
  bundle.summary.stages.governor = { technical_status: "SUCCEEDED", native_state: "BLOCKED" };
  bundle.summary.stages.navigator = { technical_status: "NOT_STARTED", native_state: null };
  bundle.summary.operator.result = null;
  bundle.summary.navigator.plan_status = null;
  bundle.summary.navigator.intake_status = null;
  bundle.summary.final_outcome = "HELD";
  bundle = withEvidence(bundle, "council_synthesis", {
    synthesis_state: "BLOCKED", advisor_count: 5,
    council_summary: "Council synthesis is BLOCKED; opportunity=NO_OPPORTUNITY_SIGNAL, permission=RESTRICTED_PERMISSION.",
    opportunity_posture: "NO_OPPORTUNITY_SIGNAL", permission_posture: "RESTRICTED_PERMISSION",
    market_structure_posture: "MIXED_MARKET_STRUCTURE", future_state_posture: "FUTURE_STATE_MISSING",
    accountability_posture: "ACCOUNTABILITY_MISSING", key_alignments: [], key_conflicts: [],
    blockers: ["mandate:READ_ONLY_DATA_RUN_NO_TRADING_AUTHORITY"],
  });
  bundle = withEvidence(bundle, "governor_rendered_decision", {
    disposition: "BLOCKED", decision_status: "RENDERED", allowed_next_step: "NONE",
    blocking_reasons: ["mandate:READ_ONLY_DATA_RUN_NO_TRADING_AUTHORITY"],
  });
  return bundle;
}

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

  it("puts the recorded Oracle narrative on the opening page without expanding exact details", () => {
    const bundle = withEvidence(readOnlyMission(), "oracle_report", {
      headline: "A recorded market headline", as_of: "2026-09-15T23:05:20Z",
      narrative_summary: { summary: "A recorded Oracle summary.", breadth_commentary: "Recorded participation commentary.",
        leadership_commentary: "Recorded leadership commentary.", rotation_commentary: "Recorded rotation commentary.",
        risk_regime_commentary: "Recorded risk commentary." },
    });
    const oracle = buildBookDefinitions(createMissionViewModel(bundle)).find((book) => book.id === "oracle")!;
    render(<BookFocus book={oracle} artifactBaseUrl="/saved/" onClose={() => {}} />);
    const narrative = within(screen.getByRole("region", { name: "Recorded Oracle market narrative" }));
    const summary = narrative.getByText("A recorded Oracle summary.");
    expect(summary).toBeVisible();
    expect(summary.closest("details")).toBeNull();
    expect(narrative.getByText("Recorded risk commentary.")).toBeVisible();
    expect(screen.getByText("Page 1 of 6")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "oracle_report.json" })).toHaveAttribute("href", "/saved/evidence/oracle_report.json");
  });

  it("keeps the source-linked model statements visible on the separate commentary page", () => {
    const bundle = withEvidence(readOnlyMission(), "oracle_modeldock_narrative", {
      summary: "Recorded model summary.", interpretation: "Recorded model interpretation.",
      confidence_explanation: "Bounded by the captured facts.", uncertainties: [], warnings: [],
      observed_facts: [{ statement: "A recorded source-linked statement.", source_artifact: "oracle_report", json_pointer: "/headline" }],
    });
    const oracle = buildBookDefinitions(createMissionViewModel(bundle)).find((book) => book.id === "oracle")!;
    render(<>{oracle.pages.find((page) => page.id === "oracle-modeldock")!.content}</>);
    const details = within(screen.getByRole("region", { name: "Recorded ModelDock narrative details" }));
    expect(details.getByText("A recorded source-linked statement.").closest("details")).toBeNull();
    expect(details.getByText(/not an assessment that uncertainty is absent/)).toBeVisible();
    expect(screen.queryByRole("region", { name: "Recorded Oracle market narrative" })).not.toBeInTheDocument();
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

  it("gives every page a plain-language reading and an initially closed exact-value disclosure", () => {
    const definitions = buildBookDefinitions(createMissionViewModel(readOnlyMission()));
    const { container } = render(<>{definitions.flatMap((book) => book.pages.map((page) => <section key={page.id}>{page.content}</section>))}</>);
    expect(screen.getAllByRole("region", { name: "Plain-language reading" })).toHaveLength(24);
    const disclosures = container.querySelectorAll("details.ledger-recorded-details");
    expect(disclosures).toHaveLength(24);
    for (const disclosure of disclosures) {
      expect(disclosure).not.toHaveAttribute("open");
      expect(disclosure.querySelector("summary")).toHaveTextContent("Recorded details · exact values");
    }
  });

  it("distinguishes Council process completion from a blocked action result", () => {
    const council = buildBookDefinitions(createMissionViewModel(readOnlyMission())).find((book) => book.id === "council")!;
    render(<>{council.pages[0].content}</>);
    const reading = within(screen.getByRole("region", { name: "Plain-language reading" }));
    expect(council.processState).toBe("Process completed");
    expect(reading.getByText("Review result: not cleared for action")).toBeInTheDocument();
    expect(reading.getByText(/a review was produced, not that action was approved/)).toBeInTheDocument();
    expect(reading.getByText(/explicit read-only mandate/)).toBeInTheDocument();
    expect(reading.getByText(/5 advisory input sources/)).toBeInTheDocument();
    expect(reading.getByText(/These are sources, not a count of AI models/)).toBeInTheDocument();
    expect(reading.getByText(/No Senate decisions were supplied/)).toBeInTheDocument();
    expect(reading.getByText(/not a finding of wrongdoing/)).toBeInTheDocument();
    expect(reading.getByText(/can still be passed to Governor/)).toBeInTheDocument();
    expect(screen.getByText("NO_OPPORTUNITY_SIGNAL").closest("details")).not.toHaveAttribute("open");
    expect(council.pages[0].evidencePaths).toEqual(["evidence/council_synthesis.json"]);
  });

  it("keeps an unfamiliar code explicit instead of manufacturing a meaning", () => {
    expect(explainRecordedCode("FUTURE_STATE_NEW")).toContain("No plain-language interpretation is defined");
    expect(explainRecordedCode("constructor")).toContain("Recorded as “constructor”");
    const bundle = withEvidence(readOnlyMission(), "council_synthesis", { synthesis_state: "UNRECOGNIZED", future_state_posture: "FUTURE_STATE_NEW" });
    const council = buildBookDefinitions(createMissionViewModel(bundle)).find((book) => book.id === "council")!;
    render(<>{council.pages[0].content}</>);
    const reading = within(screen.getByRole("region", { name: "Plain-language reading" }));
    expect(reading.getByText(/Recorded as “FUTURE_STATE_NEW”/)).toBeInTheDocument();
    expect(reading.getAllByText(/Not recorded in the supplied evidence/).length).toBeGreaterThan(0);
    expect(reading.queryByText(/market is safe/i)).not.toBeInTheDocument();
  });

  it("does not infer unanimous agreement from empty alignment and conflict lists", () => {
    const council = buildBookDefinitions(createMissionViewModel(readOnlyMission())).find((book) => book.id === "council")!;
    render(<>{council.pages[1].content}</>);
    expect(screen.getAllByText("No items listed in this artifact.")).toHaveLength(2);
    expect(screen.getByText(/do not prove unanimous agreement/)).toBeInTheDocument();
  });

  it("separates a blocked Governor result from process failure and operator approval", () => {
    const governor = buildBookDefinitions(createMissionViewModel(readOnlyMission())).find((book) => book.id === "governor")!;
    render(<>{governor.pages[0].content}{governor.pages[3].content}</>);
    expect(screen.getByText("Decision recorded: action is blocked")).toBeInTheDocument();
    expect(screen.getByText(/The Governor process completed and produced a decision/)).toBeInTheDocument();
    expect(screen.getByText("None. The decision does not authorize an onward action.")).toBeInTheDocument();
    expect(screen.getByText("No operator result is recorded.")).toBeInTheDocument();
    expect(screen.getByText(/cannot approve a handoff, place an order, or execute a trade/)).toBeInTheDocument();
  });

  it("does not substitute the supplemental market chart for a missing operational plan", () => {
    const navigator = buildBookDefinitions(createMissionViewModel(readOnlyMission())).find((book) => book.id === "navigator")!;
    render(<>{navigator.pages[0].content}{navigator.pages[2].content}</>);
    expect(screen.getByText("No operator handoff is recorded")).toBeInTheDocument();
    expect(screen.getByText("No SHADOW plan artifact is available")).toBeInTheDocument();
    expect(screen.getByText(/supplemental captured market data, not the output of an operational SHADOW plan/)).toBeInTheDocument();
  });

  it("explains the prior-measurement fallback without turning zero into observed stability", () => {
    const oracle = buildBookDefinitions(createMissionViewModel(readOnlyMission())).find((book) => book.id === "oracle")!;
    render(<>{oracle.pages[1].content}</>);
    expect(screen.getByText(/zero rotation velocity must not be read as evidence that no rotation occurred/)).toBeInTheDocument();
  });

  it("retains exact evidence links and a plain process header in the focused book", () => {
    const book = buildBookDefinitions(createMissionViewModel(readOnlyMission())).find((item) => item.id === "council")!;
    render(<BookFocus book={book} artifactBaseUrl="/saved/" onClose={() => {}} />);
    expect(screen.getByText("Mission record · Process completed")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "council_synthesis.json" })[0]).toHaveAttribute("href", "/saved/evidence/council_synthesis.json");
    expect(screen.getByRole("button", { name: "Return to full cabin" })).toBeInTheDocument();
    expect(screen.getByText("Page 1 of 4")).toBeInTheDocument();
    expect(screen.getAllByRole("region", { name: "Plain-language reading" })).toHaveLength(1);
    const inactivePage = screen.getByLabelText("Council: Agreement and dissent");
    expect(inactivePage).toHaveAttribute("inert");
    expect(inactivePage).toHaveAttribute("aria-hidden", "true");
  });
});
