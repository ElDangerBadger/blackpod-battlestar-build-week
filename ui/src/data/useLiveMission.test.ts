import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createMissionBundleFixture } from "../test/missionFixture";
import { loadLiveMissionBundle, loadLiveMissionFeed, type LiveMissionFeed } from "./liveMission";
import { evidenceFreshness, LIVE_POLL_MS, LIVE_REQUEST_TIMEOUT_MS, useLiveMission } from "./useLiveMission";

vi.mock("./liveMission", () => ({ loadLiveMissionFeed: vi.fn(), loadLiveMissionBundle: vi.fn() }));

const feed = (id = "a"): LiveMissionFeed => ({ schema_version: "blackpod.cabin_feed.v1", status: "READY",
  checked_at: "2026-09-15T20:00:00Z", message: "Verified", mission_id: "mission-001",
  observed_at: "2026-09-15T19:59:00Z", publication_id: id.repeat(64), base_url: `revisions/${id.repeat(64)}/` });
const flush = async () => { await act(async () => { await Promise.resolve(); }); };

describe("live mission following", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-15T20:00:00Z"));
    vi.mocked(loadLiveMissionFeed).mockReset().mockResolvedValue(feed());
    vi.mocked(loadLiveMissionBundle).mockReset().mockResolvedValue(createMissionBundleFixture());
  });
  afterEach(() => { vi.useRealTimers(); });

  it("polls the pointer without reloading unchanged evidence, then atomically updates a new publication", async () => {
    const { result } = renderHook(useLiveMission);
    await flush();
    const first = result.current.mission;
    expect(result.current.status).toBe("READY");
    await act(() => vi.advanceTimersByTimeAsync(LIVE_POLL_MS));
    expect(loadLiveMissionBundle).toHaveBeenCalledTimes(1);
    expect(result.current.mission).toBe(first);
    vi.mocked(loadLiveMissionFeed).mockResolvedValue(feed("b"));
    const updated = createMissionBundleFixture();
    updated.summary.snapshot_count = 14;
    vi.mocked(loadLiveMissionBundle).mockResolvedValue(updated);
    await act(() => vi.advanceTimersByTimeAsync(LIVE_POLL_MS));
    expect(result.current.mission?.status.snapshotCount).toBe(14);
    expect(loadLiveMissionBundle).toHaveBeenCalledTimes(2);
  });

  it("keeps the last verified mission visibly unavailable on failure and recovers", async () => {
    const { result } = renderHook(useLiveMission);
    await flush();
    const first = result.current.mission;
    vi.mocked(loadLiveMissionFeed).mockRejectedValueOnce(new Error("offline"));
    await act(() => vi.advanceTimersByTimeAsync(LIVE_POLL_MS));
    expect(result.current.status).toBe("UNAVAILABLE");
    expect(result.current.mission).toBe(first);
    expect(result.current.message).toBe("offline");
    await act(() => vi.advanceTimersByTimeAsync(LIVE_POLL_MS));
    expect(result.current.status).toBe("READY");
  });

  it("does not replace verified evidence with a corrupt new revision", async () => {
    const { result } = renderHook(useLiveMission);
    await flush();
    const first = result.current.mission;
    vi.mocked(loadLiveMissionFeed).mockResolvedValue(feed("b"));
    vi.mocked(loadLiveMissionBundle).mockRejectedValueOnce(new Error("hash mismatch"));
    await act(() => vi.advanceTimersByTimeAsync(LIVE_POLL_MS));
    expect(result.current.status).toBe("UNAVAILABLE");
    expect(result.current.mission).toBe(first);
    await act(() => vi.advanceTimersByTimeAsync(LIVE_POLL_MS));
    expect(loadLiveMissionBundle).toHaveBeenCalledTimes(3);
    expect(result.current.status).toBe("READY");
  });

  it("handles no source without trying a bundle or replay", async () => {
    vi.mocked(loadLiveMissionFeed).mockResolvedValue({ schema_version: "blackpod.cabin_feed.v1",
      status: "NOT_CONFIGURED", checked_at: "2026-09-15T20:00:00Z", message: "Choose a mission" });
    const { result } = renderHook(useLiveMission);
    await flush();
    expect(result.current.status).toBe("NOT_CONFIGURED");
    expect(result.current.mission).toBeNull();
    expect(loadLiveMissionBundle).not.toHaveBeenCalled();
  });

  it("bounds hung requests, prevents overlapping polls, and retries", async () => {
    vi.mocked(loadLiveMissionFeed).mockImplementationOnce(() => new Promise(() => {}));
    const { result } = renderHook(useLiveMission);
    await act(() => vi.advanceTimersByTimeAsync(LIVE_POLL_MS));
    expect(loadLiveMissionFeed).toHaveBeenCalledTimes(1);
    await act(() => vi.advanceTimersByTimeAsync(LIVE_REQUEST_TIMEOUT_MS - LIVE_POLL_MS));
    expect(result.current.status).toBe("UNAVAILABLE");
    expect(vi.mocked(loadLiveMissionFeed).mock.calls[0][0]?.signal?.aborted).toBe(true);
    await act(() => vi.advanceTimersByTimeAsync(LIVE_POLL_MS));
    expect(result.current.status).toBe("READY");
  });

  it("cancels polling on unmount and ignores late completion", async () => {
    let resolve!: (value: LiveMissionFeed) => void;
    vi.mocked(loadLiveMissionFeed).mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    const { unmount } = renderHook(useLiveMission);
    const signal = vi.mocked(loadLiveMissionFeed).mock.calls[0][0]?.signal;
    unmount();
    expect(signal?.aborted).toBe(true);
    resolve(feed());
    await flush();
    await act(() => vi.advanceTimersByTimeAsync(30_000));
    expect(loadLiveMissionFeed).toHaveBeenCalledTimes(1);
    expect(loadLiveMissionBundle).not.toHaveBeenCalled();
  });

  it("manual refresh rechecks without discarding existing evidence", async () => {
    const { result } = renderHook(useLiveMission);
    await flush();
    const first = result.current.mission;
    act(() => result.current.refresh());
    await flush();
    expect(loadLiveMissionFeed).toHaveBeenCalledTimes(2);
    expect(result.current.mission).toBe(first);
  });

  it.each(["mission_id", "observed_at"] as const)("rejects unchanged publication IDs with conflicting %s", async (field) => {
    const { result } = renderHook(useLiveMission);
    await flush();
    const first = result.current.mission;
    const verifiedAt = result.current.verifiedAt;
    vi.mocked(loadLiveMissionFeed).mockResolvedValue({ ...feed(), [field]: field === "mission_id"
      ? "different-mission" : "2026-09-15T20:00:00Z" } as LiveMissionFeed);
    await act(() => vi.advanceTimersByTimeAsync(LIVE_POLL_MS));
    expect(result.current.status).toBe("UNAVAILABLE");
    expect(result.current.mission).toBe(first);
    expect(result.current.verifiedAt).toBe(verifiedAt);
    expect(loadLiveMissionBundle).toHaveBeenCalledTimes(1);
  });

  it("separates reader health from evidence age and future clock skew", () => {
    expect(evidenceFreshness("2026-09-15T19:59:00Z")).toBe("RECENT EVIDENCE");
    expect(evidenceFreshness("2026-07-20T19:59:00Z")).toBe("STALE EVIDENCE");
    expect(evidenceFreshness("2026-09-16T00:00:00Z")).toBe("EVIDENCE CLOCK AHEAD");
    expect(evidenceFreshness("invalid")).toBe("EVIDENCE TIME UNKNOWN");
  });
});
