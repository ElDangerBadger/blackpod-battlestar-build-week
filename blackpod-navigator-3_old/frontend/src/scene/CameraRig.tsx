import { useFrame, useThree } from '@react-three/fiber';
import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { useMarket } from '../store';

/**
 * Single-parameter (zoomT in [0,1]) camera continuum:
 *   0.0  close perspective behind ship
 *   0.3  far perspective
 *   0.65 high angle
 *   1.0  top-down chart view
 *
 * Also handles:
 *  - mouse wheel zoom (modifies store.zoomT)
 *  - right-mouse drag azimuth rotation
 *  - double-click reset
 */
// Keyframes describing the camera at each anchor zoomT.
const ANCHORS = [
  // Close: cinematic over-the-shoulder, ship anchored lower-third, wake clearly visible to horizon.
  { t: 0.00, pos: new THREE.Vector3(0,   6,   -10),  look: new THREE.Vector3(0, 0,  10),  fov: 62 },
  // Far: elevated, wake reads as a long meandering ribbon along the MA bearing.
  { t: 0.30, pos: new THREE.Vector3(0,  22,   -28),  look: new THREE.Vector3(0, 0.4, 140), fov: 52 },
  // High angle: looking down at the full snake of price history.
  { t: 0.65, pos: new THREE.Vector3(0,  95,   -50),  look: new THREE.Vector3(0, 0,   260), fov: 44 },
  // Top-down: looking straight down at the center of the wake span. The camera.up
  // vector is rotated so the chart reads correctly (newest at bottom, oldest at top).
  { t: 1.00, pos: new THREE.Vector3(0, 420,    800), look: new THREE.Vector3(0, 0,   800), fov: 28 },
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

export default function CameraRig() {
  const { camera, gl } = useThree();
  const zoomT = useMarket((s) => s.zoomT);
  const setZoomT = useMarket((s) => s.setZoomT);
  const nudgeZoom = useMarket((s) => s.nudgeZoom);

  // Smoothed values
  const currentT = useRef(zoomT);
  const lookAt = useRef(new THREE.Vector3(0, 1, 30));
  const azimuth = useRef(0); // rotation around Y axis applied to camera position
  const targetAzimuth = useRef(0);
  const camUp = useRef(new THREE.Vector3(0, 1, 0));

  // Mouse wheel zoom
  useEffect(() => {
    const el = gl.domElement;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      nudgeZoom(e.deltaY * 0.0008);
    };
    const onDblClick = () => {
      setZoomT(0);
      targetAzimuth.current = 0;
    };

    let dragging = false;
    let lastX = 0;
    const onContextMenu = (e: MouseEvent) => e.preventDefault();
    const onMouseDown = (e: MouseEvent) => {
      if (e.button === 2) {
        dragging = true;
        lastX = e.clientX;
      }
    };
    const onMouseMove = (e: MouseEvent) => {
      if (!dragging) return;
      const dx = e.clientX - lastX;
      lastX = e.clientX;
      // Convert px → radians; clamp ±0.8 rad (~45°). Disabled at high zoomT.
      const maxAz = Math.max(0, 0.8 * (1 - useMarket.getState().zoomT * 1.4));
      targetAzimuth.current = THREE.MathUtils.clamp(
        targetAzimuth.current + dx * 0.005,
        -maxAz,
        maxAz,
      );
    };
    const onMouseUp = () => { dragging = false; };

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
    // Smooth zoomT
    currentT.current += (zoomT - currentT.current) * 0.08;
    // Smooth azimuth
    azimuth.current += (targetAzimuth.current - azimuth.current) * 0.1;

    const { pos, look, fov } = sampleAnchors(currentT.current);
    // Apply azimuth rotation around (0,0,0) on Y axis to pos
    const rotPos = pos.clone().applyAxisAngle(new THREE.Vector3(0, 1, 0), azimuth.current);

    camera.position.lerp(rotPos, 0.2);
    lookAt.current.lerp(look, 0.2);

    // Rotate camera.up from world-up (0,1,0) toward world-X (1,0,0) as we approach
    // top-down. This makes the top-down view read as a conventional chart:
    //   - Screen X axis = time (oldest left, newest right)
    //   - Screen Y axis = price relative to MA (above up, below down)
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