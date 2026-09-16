import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { artifact, createMissionBundleFixture } from "../test/missionFixture";
import { createMissionViewModel } from "../data/viewModel";
import type { JsonObject } from "../contracts/presentation";
import type { MissionEvidenceName } from "../data/loadMission";
import { FleetOverview } from "./FleetOverview";

function fixture() {
  const bundle = createMissionBundleFixture();
  const symbols = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLU", "XLB", "XLRE", "XLC", "SPY", "QQQ", "DIA", "VXZ", "IWF", "IWD", "IWM", "MTUM", "USMV", "QUAL"];
  const documents: Partial<Record<MissionEvidenceName, JsonObject>> = {
    oracle_normalized_snapshot: { normalized_snapshot_id: "snapshot-one", fleet_id: "fleet-oracle", as_of: "2026-09-15T23:05:20Z", symbol_count: symbols.length, symbols: symbols.map((symbol) => ({ symbol, price: symbol === "XLK" ? 183.74 : null, return_pct: null })) },
    oracle_measurement_diagnostics: { normalized_snapshot_id: "snapshot-one", items: symbols.map((symbol, index) => ({ symbol, used: index < 14, excluded: index >= 14 })) },
    council_candidate_evidence: { normalized_snapshot_id: "snapshot-one", fleet_id: "fleet-oracle", candidates: [{ symbol: "XLK", candidate_state: "OBSERVE", reasons: ["Saved observation"] }] },
  };
  const evidence = new Map(bundle.evidence);
  for (const [name, document] of Object.entries(documents)) evidence.set(name as MissionEvidenceName, { name: name as MissionEvidenceName, status: "LOADED", document, reference: artifact(name, `oracle/${name}.json`), message: null });
  bundle.evidence = evidence;
  const configured = artifact("oracle_fleet_input", "oracle/inputs/fleet.yaml");
  bundle.artifactIndex = new Map([[configured.name, configured]]);
  return { bundle, evidence, documents };
}

describe("FleetOverview", () => {
  it("renders the full observed list and separates saved coverage from membership or trading", () => {
    const { bundle } = fixture();
    render(<FleetOverview mission={createMissionViewModel(bundle)} />);
    expect(screen.getByText("21 observed symbols are listed in this mission's saved normalized snapshot.")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(22);
    expect(screen.getAllByRole("rowheader").at(-1)).toHaveTextContent("QUAL");
    expect(screen.getAllByText("Used by Oracle")).toHaveLength(14);
    expect(screen.getAllByText("Excluded from Oracle")).toHaveLength(7);
    expect(screen.getByText(/not your current Harbor registry, a portfolio/)).toBeInTheDocument();
    expect(screen.getByText(/not buy\/sell instructions/)).toBeInTheDocument();
    expect(screen.getByText("No supplemental Navigator capture is attached to this mission.")).toBeInTheDocument();
    expect(screen.getByText("183.74")).toBeInTheDocument();
    expect(screen.queryByText("$183.74")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /add|remove|trade/i })).not.toBeInTheDocument();
  });

  it("filters only the visible rows without changing records or inventing a selection", () => {
    const { bundle, documents } = fixture();
    const before = JSON.stringify(documents);
    render(<FleetOverview mission={createMissionViewModel(bundle)} />);
    const input = screen.getByRole("searchbox", { name: "Filter recorded symbols and statuses" });
    fireEvent.change(input, { target: { value: "vXz" } });
    expect(screen.getByRole("status")).toHaveTextContent("Showing 1 of 21 recorded symbols");
    expect(screen.getAllByRole("rowheader")).toHaveLength(1);
    expect(screen.getByRole("rowheader")).toHaveTextContent("VXZ");
    fireEvent.change(input, { target: { value: "unmatched" } });
    expect(screen.getByText("No recorded symbols match this filter.")).toBeInTheDocument();
    fireEvent.change(input, { target: { value: "" } });
    expect(screen.getAllByRole("rowheader")).toHaveLength(21);
    expect(JSON.stringify(documents)).toBe(before);
    expect(bundle.summary.symbol).toBe("AAPL");
  });

  it("provides safe original configured-fleet and verified JSON links", () => {
    const { bundle } = fixture();
    render(<FleetOverview mission={createMissionViewModel(bundle)} />);
    const links = within(screen.getByRole("region", { name: "Fleet source evidence" })).getAllByRole("link");
    expect(links).toHaveLength(4);
    expect(screen.getByRole("link", { name: "Configured fleet input (original file)" })).toHaveAttribute("href", "./demo/approved/oracle/inputs/fleet.yaml");
    links.forEach((link) => { expect(link).toHaveAttribute("target", "_blank"); expect(link).toHaveAttribute("rel", "noreferrer"); });
  });

  it("labels fallback diagnostic rows without promising a complete observed or configured fleet", () => {
    const { bundle, evidence } = fixture();
    evidence.delete("oracle_normalized_snapshot");
    render(<FleetOverview mission={createMissionViewModel(bundle)} />);
    expect(screen.getByText(/normalized snapshot is unavailable/)).toBeInTheDocument();
    expect(screen.queryByText("183.74")).not.toBeInTheDocument();
    expect(screen.getByText(/prices are not substituted/)).toBeInTheDocument();
    expect(screen.getAllByRole("rowheader")).toHaveLength(21);
  });

  it("renders unknown candidate strings as literal source text", () => {
    const { bundle, documents } = fixture();
    documents.council_candidate_evidence!.candidates = [{ symbol: "XLK", candidate_state: "<img src=x onerror=alert(1)>", reasons: ["<script>bad()</script>"] }];
    const { container } = render(<FleetOverview mission={createMissionViewModel(bundle)} />);
    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(screen.getByText("<script>bad()</script>")).toBeInTheDocument();
    expect(container.querySelector("img, script")).toBeNull();
  });

  it("does not seed a fleet when no evidence was supplied", () => {
    render(<FleetOverview mission={createMissionViewModel(createMissionBundleFixture())} />);
    expect(screen.getByText("No usable observed symbol list is available in the supplied mission evidence.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("offers every recorded symbol's details even without any chart captures", () => {
    const { bundle, documents } = fixture();
    const before = JSON.stringify(documents);
    const onOpenReferenceTape = vi.fn();
    const onOpenNavigator = vi.fn();
    render(<FleetOverview mission={createMissionViewModel(bundle)} onOpenReferenceTape={onOpenReferenceTape} onOpenNavigator={onOpenNavigator} />);
    expect(screen.getAllByRole("button", { name: /^View .* reference tape$/ })).toHaveLength(21);
    expect(screen.getAllByText("No chart capture")).toHaveLength(21);
    const detail = screen.getByRole("button", { name: "View VXZ reference tape" });
    expect(detail).toBeEnabled();
    expect(detail).toHaveAttribute("aria-haspopup", "dialog");
    fireEvent.click(detail);
    expect(onOpenReferenceTape).toHaveBeenCalledExactlyOnceWith("VXZ");
    expect(onOpenNavigator).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /^Review .* in Navigator$/ })).not.toBeInTheDocument();
    expect(JSON.stringify(documents)).toBe(before);
  });

  it("supports a details-only integration and filtering does not change the dispatched symbol", () => {
    const { bundle } = fixture();
    const onOpenReferenceTape = vi.fn();
    render(<FleetOverview mission={createMissionViewModel(bundle)} onOpenReferenceTape={onOpenReferenceTape} />);
    fireEvent.change(screen.getByRole("searchbox", { name: "Filter recorded symbols and statuses" }), { target: { value: "XLK" } });
    expect(screen.getByRole("columnheader", { name: "Navigator reference" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View XLK reference tape" }));
    expect(onOpenReferenceTape).toHaveBeenCalledExactlyOnceWith("XLK");
    expect(screen.getByText("183.74")).toBeInTheDocument();
  });
});
