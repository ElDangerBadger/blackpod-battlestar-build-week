import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useRef } from "react";
import * as THREE from "three";

type CameraRigProps = Readonly<{
  zoomT: number;
  reducedMotion: boolean;
  onZoomChange: (value: number) => void;
}>;

const ANCHORS = [
  { t: 0, pos: new THREE.Vector3(0, 6, 10), look: new THREE.Vector3(0, 0, -10), fov: 62 },
  { t: 0.3, pos: new THREE.Vector3(0, 16, 18), look: new THREE.Vector3(0, 0, -90), fov: 56 },
  { t: 0.65, pos: new THREE.Vector3(0, 85, 42), look: new THREE.Vector3(0, 0, -240), fov: 48 },
  { t: 1, pos: new THREE.Vector3(0, 1340, -720), look: new THREE.Vector3(0, 0, -720), fov: 66 },
] as const;

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value));
}

function easeInOutCubic(value: number): number {
  return value < 0.5 ? 4 * value ** 3 : 1 - (-2 * value + 2) ** 3 / 2;
}

function sampleCamera(value: number) {
  const t = clamp01(value);
  for (let index = 0; index < ANCHORS.length - 1; index += 1) {
    const start = ANCHORS[index];
    const end = ANCHORS[index + 1];
    if (t <= end.t) {
      const amount = easeInOutCubic((t - start.t) / (end.t - start.t));
      return {
        position: start.pos.clone().lerp(end.pos, amount),
        lookAt: start.look.clone().lerp(end.look, amount),
        fov: start.fov + (end.fov - start.fov) * amount,
      };
    }
  }
  const final = ANCHORS.at(-1)!;
  return { position: final.pos.clone(), lookAt: final.look.clone(), fov: final.fov };
}

/** Prop-driven presentation camera. Pointer listeners are scoped to the canvas. */
export function CameraRig({ zoomT, reducedMotion, onZoomChange }: CameraRigProps) {
  const { camera, gl, invalidate } = useThree();
  const currentT = useRef(reducedMotion ? zoomT : 0);
  const targetT = useRef(zoomT);
  const currentAzimuth = useRef(0);
  const targetAzimuth = useRef(0);
  const currentPan = useRef(new THREE.Vector3());
  const targetPan = useRef(new THREE.Vector3());
  const currentLook = useRef(new THREE.Vector3(0, 0, -10));
  const onZoomRef = useRef(onZoomChange);

  onZoomRef.current = onZoomChange;
  targetT.current = zoomT;

  const applyCamera = (snap: boolean) => {
    if (snap) {
      currentT.current = targetT.current;
      currentAzimuth.current = targetAzimuth.current;
      currentPan.current.copy(targetPan.current);
    } else {
      currentT.current += (targetT.current - currentT.current) * 0.08;
      currentAzimuth.current += (targetAzimuth.current - currentAzimuth.current) * 0.1;
      currentPan.current.lerp(targetPan.current, 0.12);
    }

    const target = sampleCamera(currentT.current);
    target.position.applyAxisAngle(new THREE.Vector3(0, 1, 0), currentAzimuth.current);
    target.position.add(currentPan.current);
    target.lookAt.add(currentPan.current);

    if (snap) {
      camera.position.copy(target.position);
      currentLook.current.copy(target.lookAt);
    } else {
      camera.position.lerp(target.position, 0.2);
      currentLook.current.lerp(target.lookAt, 0.2);
    }

    const topDown = THREE.MathUtils.clamp((currentT.current - 0.55) / 0.45, 0, 1);
    camera.up.set(Math.sin(topDown * Math.PI / 2), Math.cos(topDown * Math.PI / 2), 0).normalize();
    camera.lookAt(currentLook.current);
    const perspective = camera as THREE.PerspectiveCamera;
    perspective.fov = snap ? target.fov : perspective.fov + (target.fov - perspective.fov) * 0.15;
    perspective.updateProjectionMatrix();
  };

  useEffect(() => {
    if (reducedMotion) applyCamera(true);
    invalidate();
  }, [invalidate, reducedMotion, zoomT]);

  useEffect(() => {
    const element = gl.domElement;
    let drag: { pointerId: number; mode: "pan" | "rotate"; x: number; y: number } | null = null;

    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      onZoomRef.current(clamp01(targetT.current + event.deltaY * 0.0008));
    };
    const onPointerDown = (event: PointerEvent) => {
      if (event.button !== 0 && event.button !== 2) return;
      event.preventDefault();
      drag = {
        pointerId: event.pointerId,
        mode: event.button === 2 || event.shiftKey ? "rotate" : "pan",
        x: event.clientX,
        y: event.clientY,
      };
      element.setPointerCapture?.(event.pointerId);
      element.style.cursor = "grabbing";
    };
    const onPointerMove = (event: PointerEvent) => {
      if (!drag || drag.pointerId !== event.pointerId) return;
      const deltaX = event.clientX - drag.x;
      const deltaY = event.clientY - drag.y;
      drag.x = event.clientX;
      drag.y = event.clientY;
      if (drag.mode === "rotate") {
        const maximum = Math.max(0, 0.9 * (1 - targetT.current * 1.35));
        targetAzimuth.current = THREE.MathUtils.clamp(targetAzimuth.current + deltaX * 0.005, -maximum, maximum);
      } else {
        const scale = 0.04 + targetT.current * 0.6;
        targetPan.current.x = THREE.MathUtils.clamp(targetPan.current.x - deltaX * scale, -600, 600);
        targetPan.current.z = THREE.MathUtils.clamp(targetPan.current.z + deltaY * scale, -600, 600);
      }
      if (reducedMotion) applyCamera(true);
      invalidate();
    };
    const onPointerUp = (event: PointerEvent) => {
      if (!drag || drag.pointerId !== event.pointerId) return;
      element.releasePointerCapture?.(event.pointerId);
      drag = null;
      element.style.cursor = "grab";
    };
    const onDoubleClick = () => {
      targetAzimuth.current = 0;
      targetPan.current.set(0, 0, 0);
      onZoomRef.current(0);
      if (reducedMotion) applyCamera(true);
      invalidate();
    };
    const onContextMenu = (event: MouseEvent) => event.preventDefault();

    element.style.cursor = "grab";
    element.addEventListener("wheel", onWheel, { passive: false });
    element.addEventListener("pointerdown", onPointerDown);
    element.addEventListener("pointermove", onPointerMove);
    element.addEventListener("pointerup", onPointerUp);
    element.addEventListener("pointercancel", onPointerUp);
    element.addEventListener("dblclick", onDoubleClick);
    element.addEventListener("contextmenu", onContextMenu);
    return () => {
      element.removeEventListener("wheel", onWheel);
      element.removeEventListener("pointerdown", onPointerDown);
      element.removeEventListener("pointermove", onPointerMove);
      element.removeEventListener("pointerup", onPointerUp);
      element.removeEventListener("pointercancel", onPointerUp);
      element.removeEventListener("dblclick", onDoubleClick);
      element.removeEventListener("contextmenu", onContextMenu);
    };
  }, [gl, invalidate, reducedMotion]);

  useFrame(() => applyCamera(reducedMotion));
  return null;
}
