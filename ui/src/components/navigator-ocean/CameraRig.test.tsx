import { act, render } from "@testing-library/react";
import type { RenderCallback, RootState } from "@react-three/fiber";
import * as THREE from "three";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CameraRig from "./CameraRig";

const fiber = vi.hoisted(() => ({
  useFrame: vi.fn<(callback: RenderCallback) => void>(),
  useThree: vi.fn(),
}));

vi.mock("@react-three/fiber", () => fiber);

beforeEach(() => {
  fiber.useFrame.mockReset();
  fiber.useThree.mockReset();
});

function mountRig(initialZoom: number, initialReducedMotion = false) {
  const camera = new THREE.PerspectiveCamera(62, 16 / 9, 0.1, 5000);
  camera.position.set(0, 6, -10);
  const invalidate = vi.fn();
  fiber.useThree.mockReturnValue({
    camera,
    gl: { domElement: document.createElement("canvas") },
    invalidate,
  });
  const onZoomChange = vi.fn();
  const onViewChange = vi.fn<(value: number) => void>();
  let zoomT = initialZoom;
  let reducedMotion = initialReducedMotion;
  const element = () => (
    <CameraRig
      zoomT={zoomT}
      reducedMotion={reducedMotion}
      onZoomChange={onZoomChange}
      onViewChange={onViewChange}
    />
  );
  const { rerender } = render(element());
  let frameIndex = 0;

  return {
    camera,
    invalidate,
    onViewChange,
    onZoomChange,
    values: () => onViewChange.mock.calls.map(([value]) => value),
    update(nextZoom: number, nextReducedMotion = reducedMotion) {
      zoomT = nextZoom;
      reducedMotion = nextReducedMotion;
      rerender(element());
    },
    advance(frames = 1) {
      act(() => {
        for (let index = 0; index < frames; index += 1) {
          const frame = fiber.useFrame.mock.calls.at(-1)?.[0];
          if (!frame) throw new Error("CameraRig did not register a frame callback");
          // Deterministic, uneven frame timing exercises the real camera math
          // without a WebGL renderer or assumptions about a fixed frame rate.
          const delta = [1 / 60, 1 / 30, 1 / 120][frameIndex++ % 3];
          frame({ camera } as RootState, delta);
          expect([
            ...camera.position.toArray(),
            ...camera.up.toArray(),
            ...camera.quaternion.toArray(),
            ...camera.projectionMatrix.elements,
            camera.fov,
          ].every(Number.isFinite)).toBe(true);
        }
      });
    },
  };
}

function expectProgress(values: number[], start: number, target: number) {
  expect(values.length).toBeGreaterThan(1);
  let previous = start;
  for (const value of values) {
    expect(value).toBeGreaterThanOrEqual(Math.min(start, target));
    expect(value).toBeLessThanOrEqual(Math.max(start, target));
    if (target > start) expect(value).toBeGreaterThanOrEqual(previous);
    else expect(value).toBeLessThanOrEqual(previous);
    previous = value;
  }
  expect(values.at(-1)).toBe(target);
}

describe("CameraRig transitions", () => {
  it.each([
    { start: 0, target: 1, direction: "toward the chart" },
    { start: 1, target: 0, direction: "back toward the ship" },
  ])("publishes bounded, monotonic progress $direction and the exact endpoint", ({ start, target }) => {
    const rig = mountRig(start);
    rig.advance(300);
    expect(rig.onViewChange).not.toHaveBeenCalled();

    rig.update(target);
    rig.advance();
    expect(rig.values()[0]).toBeGreaterThan(Math.min(start, target));
    expect(rig.values()[0]).toBeLessThan(Math.max(start, target));
    rig.advance(299);

    expectProgress(rig.values(), start, target);
    const publications = rig.onViewChange.mock.calls.length;
    rig.advance(120);
    expect(rig.onViewChange).toHaveBeenCalledTimes(publications);
    expect(rig.onZoomChange).not.toHaveBeenCalled();
  });

  it("reverses an in-flight transition without publishing the abandoned endpoint", () => {
    const rig = mountRig(0);
    rig.update(1);
    rig.advance(10);
    const outward = rig.values();
    const turningPoint = outward.at(-1)!;
    expect(turningPoint).toBeGreaterThan(0);
    expect(turningPoint).toBeLessThan(1);

    rig.update(0);
    rig.advance(300);
    const homeward = rig.values().slice(outward.length);

    expectProgress(homeward, turningPoint, 0);
    expect(rig.values()).not.toContain(1);
    expect(rig.onViewChange.mock.calls.filter(([value]) => value === 0)).toHaveLength(1);
  });

  it("publishes a small target change even when it never crosses the normal publication threshold", () => {
    const rig = mountRig(0.5);
    rig.update(0.505);
    rig.advance(300);

    expect(rig.values()).toEqual([0.505]);

    rig.update(0.501);
    rig.advance(300);
    expect(rig.values()).toEqual([0.505, 0.501]);
  });

  it("settles the chart camera and orientation after publishing the exact chart endpoint", () => {
    const rig = mountRig(0);
    rig.update(1);
    rig.advance(300);

    expect(rig.values().at(-1)).toBe(1);
    expect(rig.camera.position.distanceTo(new THREE.Vector3(0, 3750, -820))).toBeLessThan(0.001);
    expect(rig.camera.up.distanceTo(new THREE.Vector3(1, 0, 0))).toBeLessThan(0.001);
    expect(rig.camera.getWorldDirection(new THREE.Vector3()).distanceTo(new THREE.Vector3(0, -1, 0)))
      .toBeLessThan(0.001);
    expect(Math.abs(rig.camera.fov - 27)).toBeLessThan(0.02);

    const settledPosition = rig.camera.position.clone();
    const settledRotation = rig.camera.quaternion.clone();
    rig.advance(120);
    expect(rig.camera.position.distanceTo(settledPosition)).toBeLessThan(0.001);
    expect(rig.camera.quaternion.angleTo(settledRotation)).toBeLessThan(0.001);
  });

  it("snaps both visual publication and physical camera in one frame with reduced motion", () => {
    const rig = mountRig(0, true);
    rig.update(1);
    rig.advance();

    expect(rig.values()).toEqual([1]);
    expect(rig.camera.position.toArray()).toEqual([0, 3750, -820]);
    expect(rig.camera.up.distanceTo(new THREE.Vector3(1, 0, 0))).toBeLessThan(1e-12);
    expect(rig.camera.fov).toBe(27);

    rig.update(0);
    rig.advance();
    expect(rig.values()).toEqual([1, 0]);
    expect(rig.camera.position.toArray()).toEqual([0, 7.5, 13]);
    expect(rig.camera.up.toArray()).toEqual([0, 1, 0]);
    expect(rig.camera.fov).toBe(62);

    const settledPosition = rig.camera.position.clone();
    const settledRotation = rig.camera.quaternion.clone();
    rig.advance(60);
    expect(rig.camera.position.equals(settledPosition)).toBe(true);
    expect(rig.camera.quaternion.equals(settledRotation)).toBe(true);
    expect(rig.values()).toEqual([1, 0]);
  });

  it("finishes an in-flight transition immediately when reduced motion is enabled", () => {
    const rig = mountRig(0);
    rig.update(1);
    rig.advance(10);
    expect(rig.values().at(-1)).toBeLessThan(1);

    rig.update(1, true);
    rig.advance();

    expect(rig.values().at(-1)).toBe(1);
    expect(rig.camera.position.toArray()).toEqual([0, 3750, -820]);
    expect(rig.camera.fov).toBe(27);
  });
});
