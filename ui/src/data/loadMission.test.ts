import { describe, expect, it, vi } from "vitest";
import { createMissionBundleFixture } from "../test/missionFixture";
import {
  MissionBundleLoadError,
  loadCabinPresentationSupplements,
  loadCaptainsLogMarkdownFallback,
  loadMissionBundle,
  missionRelativeUrl,
} from "./loadMission";

const WHEN = "2026-07-19T18:30:00Z";

async function digest(payload: string): Promise<string> {
  const bytes = new TextEncoder().encode(payload);
  const value = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(value)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

const correlation = {
  mission_id: "mission-cabin-context-001",
  request_id: "request-cabin-context-001",
  symbol: "AAPL",
  run_mode: "LIVE" as const,
};

describe("mission data URLs and fallback", () => {
  it("resolves only mission-relative URLs", () => {
    expect(missionRelativeUrl("./demo/approved", "presentation/mission_summary.json"))
      .toBe("./demo/approved/presentation/mission_summary.json");
    expect(() => missionRelativeUrl("./demo/approved", "../secret.json")).toThrow(/mission-relative/);
  });

  it("exposes Markdown only as read-only fallback text", async () => {
    const fetchImpl = vi.fn(async () => new Response("# Captain's Log\nCanonical prose only.", { status: 200 }));
    const fallback = await loadCaptainsLogMarkdownFallback("./demo/approved", fetchImpl as typeof fetch);

    expect(fallback).toContain("Canonical prose only.");
    expect(fetchImpl).toHaveBeenCalledWith(
      "./demo/approved/presentation/captains_log.md",
      { cache: "no-store" },
    );
  });

  it("does not convert fallback Markdown into canonical log entries", async () => {
    const bundle = createMissionBundleFixture();
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("presentation/demo_manifest.json")) {
        return new Response(JSON.stringify(bundle.manifest), { status: 200 });
      }
      if (url.endsWith("presentation/mission_summary.json")) {
        return new Response("{}", { status: 200 });
      }
      if (url.endsWith("mission_snapshot.json")) {
        return new Response("{}", { status: 200 });
      }
      if (url.endsWith("presentation/captains_log.json")) {
        return new Response("missing", { status: 404 });
      }
      if (url.endsWith("presentation/captains_log.md")) {
        return new Response("# Captain's Log\nRead-only fallback.", { status: 200 });
      }
      return new Response("missing", { status: 404 });
    });

    const error = await loadMissionBundle("./demo/approved", { fetchImpl: fetchImpl as typeof fetch })
      .then(() => null, (reason: unknown) => reason);

    expect(error).toBeInstanceOf(MissionBundleLoadError);
    expect((error as MissionBundleLoadError).fallbackMarkdown).toContain("Read-only fallback.");
    expect((error as Error).message).toMatch(/canonical Captain's Log JSON is required/);
  });
});

describe("optional cabin presentation supplements", () => {
  it("treats only a missing cabin context as honest optional absence", async () => {
    const fetchImpl = vi.fn(async () => new Response("missing", { status: 404 }));

    await expect(loadCabinPresentationSupplements("./demo/live", correlation, fetchImpl as typeof fetch))
      .resolves.toEqual({ cabinContext: null, navigatorMarket: null, portfolio: null });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("loads, hashes, and strictly parses every referenced supplement", async () => {
    const market = {
      symbol: "AAPL",
      name: "Apple Inc.",
      category: "equity",
      timeframe: "1d",
      ma_period: 250,
      currency: "USD",
      points: [
        { t: 100, o: 190, h: 192, l: 189, c: 191, v: 1000, ma: null, atr: null },
        { t: 200, o: 191, h: 194, l: 190, c: 193, v: 1200, ma: 188, atr: 3 },
      ],
      summary: {
        last_price: 193,
        last_ma: 188,
        pct_vs_ma: 2.6596,
        position: "above",
        trend_slope_pct: 0.5,
        volatility: "moderate",
        atr: 3,
        atr_pct: 1.5544,
        ma_period: 250,
        bar_count: 2,
      },
    };
    const portfolio = {
      schema_version: "blackpod.portfolio_snapshot.v1",
      captured_at: WHEN,
      source_identity: "local-paper-ledger",
      mode: "LIVE",
      account_type: "PAPER",
      currency: "USD",
      cash: 8000,
      positions: [{ symbol: "AAPL", quantity: 10, allocation_percent: 19.3 }],
    };
    const marketPayload = `${JSON.stringify(market)}\n`;
    const portfolioPayload = `${JSON.stringify(portfolio)}\n`;
    const context = {
      schema_version: "blackpod.cabin_context.v1",
      ...correlation,
      captured_at: WHEN,
      market_artifact: {
        name: "navigator_market",
        path: "presentation/navigator_market.json",
        sha256: await digest(marketPayload),
        producer: "navigator",
        byte_size: new TextEncoder().encode(marketPayload).byteLength,
        schema_version: "navigator.api.ohlc.v1",
        observed_at: WHEN,
      },
      portfolio_artifact: {
        name: "portfolio_snapshot",
        path: "presentation/portfolio_snapshot.json",
        sha256: await digest(portfolioPayload),
        producer: "portfolio",
        byte_size: new TextEncoder().encode(portfolioPayload).byteLength,
        schema_version: "blackpod.portfolio_snapshot.v1",
        observed_at: WHEN,
      },
      capture_provenance: {
        market: {
          status: "CAPTURED",
          transport: "LOCAL_JSON",
          source_identity: "navigator-fixture-aapl",
          navigator_git_revision: "b".repeat(40),
        },
        portfolio: {
          status: "CAPTURED",
          transport: "LOCAL_JSON",
          source_identity: "local-paper-ledger",
        },
      },
    };
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("presentation/cabin_context.json")) {
        return new Response(JSON.stringify(context), { status: 200 });
      }
      if (url.endsWith("presentation/navigator_market.json")) {
        return new Response(marketPayload, { status: 200 });
      }
      if (url.endsWith("presentation/portfolio_snapshot.json")) {
        return new Response(portfolioPayload, { status: 200 });
      }
      return new Response("missing", { status: 404 });
    });

    const loaded = await loadCabinPresentationSupplements("./demo/live", correlation, fetchImpl as typeof fetch);

    expect(loaded.cabinContext?.capture_provenance.market.status).toBe("CAPTURED");
    expect(loaded.navigatorMarket?.summary.last_price).toBe(193);
    expect(loaded.portfolio?.source_identity).toBe("local-paper-ledger");

    const replayContext = { ...context, run_mode: "REPLAY" };
    const replayFetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("presentation/cabin_context.json")) {
        return new Response(JSON.stringify(replayContext), { status: 200 });
      }
      if (url.endsWith("presentation/navigator_market.json")) {
        return new Response(marketPayload, { status: 200 });
      }
      if (url.endsWith("presentation/portfolio_snapshot.json")) {
        return new Response(portfolioPayload, { status: 200 });
      }
      return new Response("missing", { status: 404 });
    });
    await expect(loadCabinPresentationSupplements(
      "./demo/approved",
      { ...correlation, run_mode: "REPLAY" },
      replayFetch as typeof fetch,
    )).rejects.toThrow(/portfolio mode must be LIVE for LIVE missions and FROZEN for REPLAY/);
  });

  it("rejects corrupted referenced bytes instead of falling back", async () => {
    const context = {
      schema_version: "blackpod.cabin_context.v1",
      ...correlation,
      captured_at: WHEN,
      market_artifact: {
        name: "navigator_market",
        path: "presentation/navigator_market.json",
        sha256: "a".repeat(64),
        producer: "navigator",
        byte_size: 2,
        schema_version: "navigator.api.ohlc.v1",
        observed_at: WHEN,
      },
      portfolio_artifact: null,
      capture_provenance: {
        market: {
          status: "CAPTURED",
          transport: "HTTP",
          source_identity: "navigator-local-api",
          navigator_git_revision: "b".repeat(40),
        },
        portfolio: { status: "NOT_CONFIGURED", transport: null, source_identity: null },
      },
    };
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => String(input).endsWith("cabin_context.json")
      ? new Response(JSON.stringify(context), { status: 200 })
      : new Response("{}", { status: 200 }));

    await expect(loadCabinPresentationSupplements("./demo/live", correlation, fetchImpl as typeof fetch))
      .rejects.toThrow(/SHA-256 does not match|byte size does not match/);
  });
});
