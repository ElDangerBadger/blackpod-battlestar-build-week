import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMissionViewModel } from "../data/viewModel";
import { createMissionBundleFixture } from "../test/missionFixture";
import { navigatorReferenceFixture, REFERENCE_NOW, REFERENCE_PUBLICATION } from "../test/navigatorReferenceFixture";
import { NavigatorOceanBoundary } from "./NavigatorOceanBoundary";
import { NavigatorReferenceTape } from "./NavigatorReferenceTape";
import type { NavigatorOceanViewProps } from "./navigator-ocean/NavigatorOceanView";

// The current completed-bar source is independent of the separately tested
// Alpaca trade stream. This suite makes only the selected reference GET.
vi.mock("../data/useLiveNavigatorPrice", () => ({ useLiveNavigatorPrice: () => ({ status: "WAITING", event: null, quote: null }) }));

function savedMarket() {
  const market = navigatorReferenceFixture().snapshot!.market;
  market.points.at(-1)!.c = 330;
  market.summary.last_price = 330;
  return market;
}
function mission() {
  const value = createMissionViewModel(createMissionBundleFixture());
  value.baseUrl = `/live/revisions/${REFERENCE_PUBLICATION}/`;
  value.status.runMode = "LIVE";
  value.market = { ...value.market, status: "CAPTURED", navigatorMarket: savedMarket(), capturedAt: "2026-09-15T22:00:00Z", sourceIdentity: "original mission" };
  return value;
}
const liveProps = { presentationMode: "LIVE" as const, runMode: "LIVE" as const, capturedAt: "2026-09-15T22:00:00Z", reducedMotion: true, livePublicationId: REFERENCE_PUBLICATION };
const View = (props: NavigatorOceanViewProps) => <p>Rendered {props.data.symbol} {props.data.timeframe} MA{props.data.ma_period}: {props.data.summary.last_price} at {props.capturedAt}</p>;
const loadView = async () => ({ default: View });
const response = () => new Response(JSON.stringify(navigatorReferenceFixture()));

describe("Navigator current history source", () => {
  beforeEach(() => { vi.spyOn(Date, "now").mockReturnValue(Date.parse(REFERENCE_NOW)); });
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it("defaults LIVE to current completed bars, preserves saved capture, and keeps price-source controls independent", async () => {
    const original = savedMarket(), before = JSON.stringify(original);
    const fetch = vi.fn(async () => response()); vi.stubGlobal("fetch", fetch);
    render(<NavigatorOceanBoundary {...liveProps} data={original} capabilityProbe={() => true} loadView={loadView} />);
    expect(await screen.findByText(/Rendered AAPL 1d MA250: 334 at 2026-09-18T14:59:00Z/)).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(1);
    const source = screen.getByLabelText("Navigator history reference source");
    expect(source).toHaveTextContent("CURRENT REFERENCE · READY");
    expect(source.querySelector("details")).not.toHaveAttribute("open");
    fireEvent.click(screen.getByRole("button", { name: "Captured reference" }));
    expect(screen.getByText(/Showing the selected reference only/)).toBeInTheDocument();
    expect(screen.getByText(/Rendered AAPL 1d MA250: 334/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Saved reference" }));
    expect(screen.getByText(/Rendered AAPL 1d MA250: 330 at 2026-09-15T22:00:00Z/)).toBeInTheDocument();
    expect(source).toHaveTextContent("SAVED MISSION REFERENCE");
    expect(fetch).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Current reference" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByRole("button", { name: "Original mission capture" }));
    expect(screen.getByText(/Rendered AAPL 1d MA250: 330 at 2026-09-15T22:00:00Z/)).toBeInTheDocument();
    expect(JSON.stringify(original)).toBe(before);
  });

  it("keeps unavailable current source explicit and shows the saved chart without inventing replacement data", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ...navigatorReferenceFixture(), status: "NOT_CONFIGURED", snapshot: null, message: "Current reference is not configured." }))));
    render(<NavigatorOceanBoundary {...liveProps} data={savedMarket()} capabilityProbe={() => true} loadView={loadView} />);
    expect(await screen.findByText("CURRENT REFERENCE · NOT_CONFIGURED")).toBeInTheDocument();
    expect(screen.getByText(/Showing the saved capture until a valid current reference/)).toBeInTheDocument();
    expect(await screen.findByText(/Rendered AAPL 1d MA250: 330/)).toBeInTheDocument();
  });

  it("updates the expanded tape from current reference while keeping original mission data intact", async () => {
    const original = mission(), before = JSON.stringify(original.market);
    vi.stubGlobal("fetch", vi.fn(async () => response()));
    const open = vi.fn();
    render(<NavigatorReferenceTape mission={original} presentationMode="LIVE" onOpenNavigator={open} />);
    expect(await screen.findByText("CURRENT REFERENCE · READY")).toBeInTheDocument();
    expect(within(screen.getByLabelText("Price snapshot")).getByText("$334.00")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open full Navigator" }));
    expect(open).toHaveBeenCalledWith("AAPL", { symbol: "AAPL", timeframe: "1d", ma_period: 250, referenceMode: "CURRENT" });
    fireEvent.click(screen.getByRole("button", { name: "Saved reference" }));
    expect(within(screen.getByLabelText("Price snapshot")).getByText("$330.00")).toBeInTheDocument();
    expect(screen.getByText(/Opening this module does not refresh either timestamp/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open full Navigator" }));
    expect(open).toHaveBeenLastCalledWith("AAPL", { symbol: "AAPL", timeframe: "1d", ma_period: 250, referenceMode: "SAVED" });
    expect(JSON.stringify(original.market)).toBe(before);
  });

  it("never fetches current references in DEMO even when the record is LIVE", () => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    render(<><NavigatorOceanBoundary {...liveProps} presentationMode="DEMO" data={savedMarket()} capabilityProbe={() => false} />
      <NavigatorReferenceTape mission={mission()} presentationMode="DEMO" onOpenNavigator={vi.fn()} /></>);
    expect(fetch).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("Navigator history reference source")).not.toBeInTheDocument();
  });
  it("does not infer LIVE authorization when the tape presentation mode is omitted", () => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    render(<NavigatorReferenceTape mission={mission()} onOpenNavigator={vi.fn()} />);
    expect(fetch).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("Navigator history reference source")).not.toBeInTheDocument();
  });
});
