import { describe, expect, it, vi } from "vitest";
import { createMissionBundleFixture } from "../test/missionFixture";
import {
  MissionBundleLoadError,
  loadCaptainsLogMarkdownFallback,
  loadMissionBundle,
  missionRelativeUrl,
} from "./loadMission";

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
