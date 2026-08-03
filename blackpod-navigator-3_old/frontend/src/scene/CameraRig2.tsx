import { useFrame, useThree } from '@react-three/fiber';
import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { useMarket } from '../store';

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
  // Close: cinematic over-the-shoulder. Ship dominates lower-third; wake visible to horizon.
  { t: 0.00, pos: new THREE.Vector3(0,   6,    10),  look: new THREE.Vector3(0, 0,   -10),  fov: 62 },
  // Far: elevated view that KEEPS the ship in lower-frame as anchor; wake/MA bow visible.
  { t: 0.30, pos: new THREE.Vector3(0,  16,    18),  look: new THREE.Vector3(0, 0,   -90),  fov: 56 },
  // High angle: full snake of price history; ship at bottom-third of frame.
  { t: 0.65, pos: new THREE.Vector3(0,  85,    42),  look: new THREE.Vector3(0, 0,  -240),  fov: 48 },
  // Top-down: framed so the FULL wake (ship at Z=0 → oldest at Z≈-1600) fits in view.
  // Looking straight down with up=+X → time on screen-X (ship RIGHT, oldest LEFT), price on screen-Y.
  // Look-at biased toward the ship (z=-720) so the current-price marker has right-edge margin.
  { t: 1.00, pos: new THREE.Vector3(0, 1340, -720),  look: new THREE.Vector3(0, 0,  -720),  fov: 66 },
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

export default function CameraRig2() {
  const { camera, gl } = useThree();
  const zoomT = useMarket((s) => s.zoomT);
  const setZoomT = useMarket((s) => s.setZoomT);
  const setViewT = useMarket((s) => s.setViewT);
  const nudgeZoom = useMarket((s) => s.nudgeZoom);
  const lastViewWrite = useRef(0.1);

  const currentT = useRef(zoomT);
  const lookAt = useRef(new THREE.Vector3(0, 1, 30));
  const azimuth = useRef(0);
  const targetAzimuth = useRef(0);
  const camUp = useRef(new THREE.Vector3(0, 1, 0));
  const pan = useRef(new THREE.Vector3(0, 0, 0));
  const targetPan = useRef(new THREE.Vector3(0, 0, 0));

  useEffect(() => {
    const el = gl.domElement;

    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      nudgeZoom(e.deltaY * 0.0008);
    };
    const onDblClick = () => {
      setZoomT(0);
      targetAzimuth.current = 0;
      targetPan.current.set(0, 0, 0);
    };
    const onContextMenu = (e: MouseEvent) => e.preventDefault();

    // Interaction state
    let leftDragging = false;
    let rightDragging = false;
    let lastX = 0;
    let lastY = 0;

    const onMouseDown = (e: MouseEvent) => {
      if (e.button === 0) {
        // Left-drag panning
        leftDragging = true;
        lastX = e.clientX;
        lastY = e.clientY;
        el.style.cursor = 'grabbing';
      } else if (e.button === 2) {
        rightDragging = true;
        lastX = e.clientX;
      }
    };
    const onMouseMove = (e: MouseEvent) => {
      if (rightDragging) {
        const dx = e.clientX - lastX;
        lastX = e.clientX;
        const z = useMarket.getState().zoomT;
        const maxAz = Math.max(0, 0.9 * (1 - z * 1.35));
        targetAzimuth.current = THREE.MathUtils.clamp(
          targetAzimuth.current + dx * 0.005,
          -maxAz,
          maxAz,
        );
      } else if (leftDragging) {
        const dx = e.clientX - lastX;
        const dy = e.clientY - lastY;
        lastX = e.clientX;
        lastY = e.clientY;
        // Pan scale grows with the camera's altitude
        const z = useMarket.getState().zoomT;
        const altitudeScale = 0.04 + z * 0.6;
        targetPan.current.x -= dx * altitudeScale;
        // dy → world Z (forward/back) at low zoom, world Y at top-down
        targetPan.current.z += dy * altitudeScale;
        // Clamp to keep ship reachable (cap at ±world width)
        const cap = 600;
        targetPan.current.x = THREE.MathUtils.clamp(targetPan.current.x, -cap, cap);
        targetPan.current.z = THREE.MathUtils.clamp(targetPan.current.z, -cap, cap);
      }
    };
    const onMouseUp = (e: MouseEvent) => {
      if (e.button === 0) {
        leftDragging = false;
        el.style.cursor = 'grab';
      }
      if (e.button === 2) rightDragging = false;
    };

    el.style.cursor = 'grab';
    el.addEventListener('wheel', onWheel, { passive: false });
    el.addEventListener('dblclick', onDblClick);
    el.addEventListener('contextmenu', onContextMenu);
    el.addEventListener('mousedown', onMouseDown);
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    return () => {
      el.removeEventListener('wheel', onWheel);
      el.removeEventListener('dblclick', onDblClick);
      el.removeEventListener('contextmenu', onContextMenu);
      el.removeEventListener('mousedown', onMouseDown);
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
  }, [gl, nudgeZoom, setZoomT]);

  useFrame(() => {
    currentT.current += (zoomT - currentT.current) * 0.08;
    azimuth.current += (targetAzimuth.current - azimuth.current) * 0.1;
    pan.current.lerp(targetPan.current, 0.12);

    // Publish the smoothed camera param so geometry (chart stretch) can follow the
    // same easing as the camera. Throttle writes to limit Line2 geometry rebuilds.
    if (Math.abs(currentT.current - lastViewWrite.current) > 0.012) {
      lastViewWrite.current = currentT.current;
      setViewT(currentT.current);
    }

    const { pos, look, fov } = sampleAnchors(currentT.current);
    const rotPos = pos.clone().applyAxisAngle(new THREE.Vector3(0, 1, 0), azimuth.current);
    rotPos.add(pan.current);
    const lookPanned = look.clone().add(pan.current);

    camera.position.lerp(rotPos, 0.2);
    lookAt.current.lerp(lookPanned, 0.2);

    // Up-vector rotation for top-down chart orientation.
    const tNorm = THREE.MathUtils.clamp((currentT.current - 0.55) / 0.45, 0, 1);
    const angle = (tNorm * Math.PI) / 2;
    const targetUp = new THREE.Vector3(Math.sin(angle), Math.cos(angle), 0).normalize();
    camUp.current.lerp(targetUp, 0.12).normalize();
    camera.up.copy(camUp.current);

    camera.lookAt(lookAt.current);

    const persp = camera as THREE.PerspectiveCamera;
    if (Math.abs(persp.fov - fov) > 0.01) {
      persp.fov += (fov - persp.fov) * 0.15;
      persp.updateProjectionMatrix();
    }
  });

  return null;
}