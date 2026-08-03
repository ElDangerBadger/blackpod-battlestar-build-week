import { useFrame, useThree } from '@react-three/fiber';
import { useEffect, useRef } from 'react';
import * as THREE from 'three';

/**
 * Single-parameter (zoomT in [0,1]) camera continuum + interaction:
 *
 *  Anchors:
 *    0.00  close perspective behind ship
 *    0.30  far perspective
 *    0.65  high angle
 *    1.00  top-down chart view
 *
 *  Inputs:
 *    - mouse wheel        → zoomT
 *    - right-mouse drag   → azimuth (rotate camera around vertical axis)
 *    - left-mouse drag    → pan (offset both camera and lookAt in world space)
 *    - double-click       → reset zoom + pan + rotation
 *
 *  At zoomT ≥ 0.55 the camera up-vector rotates from world-up to world-X so the
 *  top-down view reads as a conventional chart (time on screen-X, price on screen-Y).
 */
// NOTE: the wake trails into NEGATIVE Z (see projection.ts). The camera therefore
// sits at POSITIVE Z (in front of the ship) looking back along -Z toward the horizon.
const ANCHORS = [
  // Close: cinematic over-the-shoulder. Pulled back + raised so the full man o'
  // war rig (masts + sails) frames without clipping the top; wake to horizon.
  { t: 0.00, pos: new THREE.Vector3(0,   7.5,  13),  look: new THREE.Vector3(0, 2.4, -10),  fov: 62 },
  // Far: elevated view that KEEPS the ship in lower-frame as anchor; raised the
  // look-at so the tall silhouette sits fully in frame; wake/MA bow visible.
  { t: 0.30, pos: new THREE.Vector3(0,  19,    26),  look: new THREE.Vector3(0, 5,   -90),  fov: 56 },
  // High angle: full snake of price history; ship at bottom-third of frame.
  { t: 0.65, pos: new THREE.Vector3(0,  85,    42),  look: new THREE.Vector3(0, 0,  -240),  fov: 48 },
  // Top-down: framed so the FULL wake (ship at Z=0 → oldest at Z≈-1600) fits in view.
  // Looking straight down with up=+X. Camera raised high + NARROW fov so the view
  // reads as a near-orthographic FLAT chart (minimal perspective convergence)
  // rather than a receding ocean plane. Centred on the middle of the span.
  { t: 1.00, pos: new THREE.Vector3(0, 3750, -820),  look: new THREE.Vector3(0, 0,  -820),  fov: 27 },
];

function easeInOutCubic(t: number) {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

function sampleAnchors(t: number) {
  for (let i = 0; i < ANCHORS.length - 1; i++) {
    const a = ANCHORS[i];
    const b = ANCHORS[i + 1];
    if (t <= b.t) {
      const k = (t - a.t) / (b.t - a.t);
      const e = easeInOutCubic(k);
      const pos = a.pos.clone().lerp(b.pos, e);
      const look = a.look.clone().lerp(b.look, e);
      const fov = a.fov + (b.fov - a.fov) * e;
      return { pos, look, fov };
    }
  }
  const last = ANCHORS[ANCHORS.length - 1];
  return { pos: last.pos.clone(), look: last.look.clone(), fov: last.fov };
}

export interface CameraRigProps {
  zoomT: number;
  reducedMotion: boolean;
  onZoomChange: (value: number) => void;
  onViewChange: (value: number) => void;
}

function clamp01(value: number) {
  return THREE.MathUtils.clamp(value, 0, 1);
}

export default function CameraRig({
  zoomT,
  reducedMotion,
  onZoomChange,
  onViewChange,
}: CameraRigProps) {
  const { camera, gl, invalidate } = useThree();
  const lastViewWrite = useRef(zoomT);
  const zoomRef = useRef(zoomT);

  const currentT = useRef(zoomT);
  const lookAt = useRef(new THREE.Vector3(0, 1, 30));
  const azimuth = useRef(0);
  const targetAzimuth = useRef(0);
  const camUp = useRef(new THREE.Vector3(0, 1, 0));
  const pan = useRef(new THREE.Vector3(0, 0, 0));
  const targetPan = useRef(new THREE.Vector3(0, 0, 0));
  const breatheT = useRef(0);

  useEffect(() => {
    zoomRef.current = zoomT;
    invalidate();
  }, [invalidate, zoomT]);

  useEffect(() => {
    const el = gl.domElement;
    const previousCursor = el.style.cursor;
    const previousTouchAction = el.style.touchAction;

    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      onZoomChange(clamp01(zoomRef.current + e.deltaY * 0.0008));
      invalidate();
    };
    const onDblClick = () => {
      onZoomChange(0);
      targetAzimuth.current = 0;
      targetPan.current.set(0, 0, 0);
      invalidate();
    };
    const onContextMenu = (e: MouseEvent) => e.preventDefault();

    let dragMode: 'pan' | 'rotate' | null = null;
    let pointerId: number | null = null;
    let lastX = 0;
    let lastY = 0;

    const onPointerDown = (e: PointerEvent) => {
      e.preventDefault();
      if (e.button === 0) {
        dragMode = e.shiftKey ? 'rotate' : 'pan';
        lastX = e.clientX;
        lastY = e.clientY;
        el.style.cursor = dragMode === 'rotate' ? 'ew-resize' : 'grabbing';
      } else if (e.button === 2) {
        dragMode = 'rotate';
        lastX = e.clientX;
      } else {
        return;
      }
      pointerId = e.pointerId;
      el.setPointerCapture?.(e.pointerId);
    };
    const onPointerMove = (e: PointerEvent) => {
      if (e.pointerId !== pointerId) return;
      if (dragMode === 'rotate') {
        const dx = e.clientX - lastX;
        lastX = e.clientX;
        const z = zoomRef.current;
        const maxAz = Math.max(0, 0.9 * (1 - z * 1.35));
        targetAzimuth.current = THREE.MathUtils.clamp(
          targetAzimuth.current + dx * 0.005,
          -maxAz,
          maxAz,
        );
      } else if (dragMode === 'pan') {
        const dx = e.clientX - lastX;
        const dy = e.clientY - lastY;
        lastX = e.clientX;
        lastY = e.clientY;
        const z = zoomRef.current;
        const altitudeScale = 0.04 + z * 0.6;
        targetPan.current.x -= dx * altitudeScale;
        targetPan.current.z += dy * altitudeScale;
        const cap = 600;
        targetPan.current.x = THREE.MathUtils.clamp(targetPan.current.x, -cap, cap);
        targetPan.current.z = THREE.MathUtils.clamp(targetPan.current.z, -cap, cap);
      }
      invalidate();
    };
    const onPointerUp = (e: PointerEvent) => {
      if (e.pointerId !== pointerId) return;
      el.releasePointerCapture?.(e.pointerId);
      dragMode = null;
      pointerId = null;
      el.style.cursor = 'grab';
      invalidate();
    };

    el.style.cursor = 'grab';
    el.style.touchAction = 'none';
    el.addEventListener('wheel', onWheel, { passive: false });
    el.addEventListener('dblclick', onDblClick);
    el.addEventListener('contextmenu', onContextMenu);
    el.addEventListener('pointerdown', onPointerDown);
    el.addEventListener('pointermove', onPointerMove);
    el.addEventListener('pointerup', onPointerUp);
    el.addEventListener('pointercancel', onPointerUp);
    return () => {
      el.style.cursor = previousCursor;
      el.style.touchAction = previousTouchAction;
      el.removeEventListener('wheel', onWheel);
      el.removeEventListener('dblclick', onDblClick);
      el.removeEventListener('contextmenu', onContextMenu);
      el.removeEventListener('pointerdown', onPointerDown);
      el.removeEventListener('pointermove', onPointerMove);
      el.removeEventListener('pointerup', onPointerUp);
      el.removeEventListener('pointercancel', onPointerUp);
    };
  }, [gl, invalidate, onZoomChange]);

  useFrame((_, delta) => {
    const cameraEase = reducedMotion ? 1 : 0.08;
    const interactionEase = reducedMotion ? 1 : 0.12;
    currentT.current += (zoomT - currentT.current) * cameraEase;
    azimuth.current += (targetAzimuth.current - azimuth.current) * (reducedMotion ? 1 : 0.1);
    pan.current.lerp(targetPan.current, interactionEase);
    if (!reducedMotion) breatheT.current += delta;

    // Publish the smoothed camera param so geometry (chart stretch) can follow the
    // same easing as the camera. Throttle writes to limit Line2 geometry rebuilds.
    const remaining = Math.abs(currentT.current - zoomT);
    const publishFinalTarget = remaining < 0.001
      && Math.abs(zoomT - lastViewWrite.current) > Number.EPSILON;
    if (Math.abs(currentT.current - lastViewWrite.current) > 0.012 || publishFinalTarget) {
      const publishedView = publishFinalTarget ? zoomT : currentT.current;
      lastViewWrite.current = publishedView;
      onViewChange(publishedView);
    }

    const { pos, look, fov } = sampleAnchors(currentT.current);
    const rotPos = pos.clone().applyAxisAngle(new THREE.Vector3(0, 1, 0), azimuth.current);
    rotPos.add(pan.current);
    const lookPanned = look.clone().add(pan.current);

    // Cinematic handheld "breathing" — a slow, layered drift on the camera (and
    // a fainter one on the look target for parallax). Full in the 3D vantages,
    // eased to zero as we flatten to the analytical chart so it stays rock-steady.
    const breatheGate = 1 - THREE.MathUtils.smoothstep(currentT.current, 0.55, 1.0);
    if (!reducedMotion && breatheGate > 0.001) {
      const bt = breatheT.current;
      const bx = Math.sin(bt * 0.47) * 0.55 + Math.sin(bt * 0.23 + 1.3) * 0.28;
      const by = Math.cos(bt * 0.39) * 0.42 + Math.sin(bt * 0.6 + 0.7) * 0.14;
      const amt = breatheGate;
      rotPos.x += bx * amt;
      rotPos.y += by * amt;
      lookPanned.x += bx * 0.45 * amt;
      lookPanned.y += by * 0.35 * amt;
    }

    if (reducedMotion) {
      camera.position.copy(rotPos);
      lookAt.current.copy(lookPanned);
    } else {
      camera.position.lerp(rotPos, 0.2);
      lookAt.current.lerp(lookPanned, 0.2);
    }

    // Up-vector rotation for top-down chart orientation.
    const tNorm = THREE.MathUtils.clamp((currentT.current - 0.55) / 0.45, 0, 1);
    const angle = (tNorm * Math.PI) / 2;
    const targetUp = new THREE.Vector3(Math.sin(angle), Math.cos(angle), 0).normalize();
    camUp.current.lerp(targetUp, reducedMotion ? 1 : 0.12).normalize();
    camera.up.copy(camUp.current);

    camera.lookAt(lookAt.current);

    const persp = camera as THREE.PerspectiveCamera;
    if (Math.abs(persp.fov - fov) > 0.01) {
      persp.fov += (fov - persp.fov) * (reducedMotion ? 1 : 0.15);
      persp.updateProjectionMatrix();
    }
  });

  return null;
}
