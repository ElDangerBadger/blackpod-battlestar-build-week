import { useLayoutEffect, useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import type { NavigatorOceanVolatility } from './types';
import { sampleOceanSurface, volatilityIntensity } from './oceanHeight';
import { SHIP_RENDER_ORDER } from './renderOrder';
import BowWake from './BowWake';
import Spray from './Spray';

export interface ShipProps {
  scale?: number;
  volatility?: NavigatorOceanVolatility;
  zoomT?: number;
  reducedMotion?: boolean;
}

/**
 * Procedural wooden man o' war — a three-masted, square-rigged ship of the line
 * in the age-of-sail tradition (think a Nelson-era first-rate).
 *
 * Coordinate frame (LOCAL, before the group's PI-about-Y flip):
 *   +Z = bow (pointed, with bowsprit)   -Z = stern (raised aftercastle + gallery)
 *   +Y = up                              ±X = starboard / port beams
 *
 * The hull group is rotated PI about Y, so LOCAL +Z (bow) maps to WORLD -Z
 * (toward the horizon). The camera sits on the +Z world side, so the viewer
 * mostly sees the ornate stern gallery — the wake (price history) trails from
 * the stern toward the camera.
 *
 * IMPORTANT: the buoyancy / wave-riding logic (sampleOceanSurface + damped
 * motion + separate flat foam group) is unchanged from the prior vessel so the
 * ship still rides the exact ocean-shader surface and the buoyancy tests hold.
 */

// ---- Shared material presets ------------------------------------------------
const WOOD_SPAR = { color: '#3d2916', roughness: 0.6, metalness: 0.05, envMapIntensity: 0.8 } as const;
const WOOD_DECK = { color: '#b0894f', roughness: 0.74, metalness: 0.02, envMapIntensity: 0.7 } as const;
const WOOD_TRIM = { color: '#5a3a20', roughness: 0.66, metalness: 0.05, envMapIntensity: 0.8 } as const;
const GOLD = { color: '#c9a24a', roughness: 0.34, metalness: 0.92, envMapIntensity: 1.5 } as const;
const SAIL = {
  color: '#e9e1cf',
  roughness: 0.94,
  metalness: 0.0,
  side: THREE.DoubleSide,
  emissive: '#2b2416',
  emissiveIntensity: 0.05,
} as const;
const RIGGING = { color: '#1c140c', roughness: 0.8, metalness: 0.0 } as const;

// ---- Geometry helpers -------------------------------------------------------
/** A gently billowing square sail — a plane bowed toward +Z (forward). */
function bowedSailGeom(w: number, h: number, bow = 0.16) {
  const g = new THREE.PlaneGeometry(w, h, 12, 3);
  const p = g.attributes.position as THREE.BufferAttribute;
  for (let i = 0; i < p.count; i++) {
    const x = p.getX(i);
    const y = p.getY(i);
    const nx = x / (w / 2);
    const ny = y / (h / 2);
    // Bulge in the middle, pinned at the edges (bolt-ropes / yard + foot).
    p.setZ(i, (1 - nx * nx) * (1 - 0.35 * ny * ny) * bow);
  }
  p.needsUpdate = true;
  g.computeVertexNormals();
  return g;
}

/** A flat triangular staysail / jib from three local-space points. */
function triGeom(a: [number, number, number], b: [number, number, number], c: [number, number, number]) {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute([...a, ...b, ...c], 3));
  g.computeVertexNormals();
  return g;
}

/** Build a thin rigging line (Y-axis cylinder) oriented between two points. */
function riggingProps(a: THREE.Vector3, b: THREE.Vector3) {
  const mid = a.clone().add(b).multiplyScalar(0.5);
  const dir = b.clone().sub(a);
  const len = dir.length();
  const quat = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.clone().normalize());
  const e = new THREE.Euler().setFromQuaternion(quat);
  return { position: [mid.x, mid.y, mid.z] as [number, number, number], rotation: [e.x, e.y, e.z] as [number, number, number], len };
}

// ---- A single mast with its yards, square sails and shrouds ----------------
function MastRig({
  z,
  height,
  lowerW,
  upperW,
  base = 0.22,
  reducedMotion = false,
}: {
  z: number;
  height: number;
  lowerW: number;
  upperW: number;
  base?: number;
  reducedMotion?: boolean;
}) {
  const lowH = height * 0.42;
  const upH = height * 0.34;
  const geoms = useMemo(
    () => ({ low: bowedSailGeom(lowerW, lowH), up: bowedSailGeom(upperW, upH) }),
    [lowerW, upperW, lowH, upH],
  );

  const lowYardY = base + height * 0.46;
  const upYardY = base + height * 0.78;
  const lowSailY = lowYardY - lowH / 2 - 0.03;
  const upSailY = upYardY - upH / 2 - 0.03;

  // Sail luffing: gently breathe the billow depth (scale.z) and shiver the sail
  // about the mast so the canvas looks alive in the wind. Phase keyed off the
  // mast's z so the three masts don't pulse in lockstep.
  const lowSail = useRef<THREE.Mesh>(null);
  const upSail = useRef<THREE.Mesh>(null);
  useFrame((state) => {
    const t = (reducedMotion ? 0 : state.clock.elapsedTime) + z * 1.7;
    const breatheLo = 1 + Math.sin(t * 1.6) * 0.16 + Math.sin(t * 3.7) * 0.05;
    const breatheHi = 1 + Math.sin(t * 1.9 + 0.8) * 0.18 + Math.sin(t * 4.3) * 0.06;
    const shiverLo = Math.sin(t * 2.3) * 0.04;
    const shiverHi = Math.sin(t * 2.7 + 1.1) * 0.05;
    if (lowSail.current) {
      lowSail.current.scale.z = breatheLo;
      lowSail.current.rotation.y = shiverLo;
    }
    if (upSail.current) {
      upSail.current.scale.z = breatheHi;
      upSail.current.rotation.y = shiverHi;
    }
  });

  // Shrouds (standing rigging) fan from below the top down to the channels.
  const shroudTopY = base + height * 0.7;
  const shrouds = useMemo(() => {
    const anchors = [
      { x: 0.34, z: 0.18 },
      { x: 0.34, z: -0.18 },
      { x: -0.34, z: 0.18 },
      { x: -0.34, z: -0.18 },
    ];
    return anchors.map((s) =>
      riggingProps(new THREE.Vector3(s.x, base + 0.02, s.z), new THREE.Vector3(0, shroudTopY, 0)),
    );
  }, [base, shroudTopY]);

  return (
    <group position={[0, 0, z]}>
      {/* Lower mast (tapered) */}
      <mesh position={[0, base + height / 2, 0]} castShadow>
        <cylinderGeometry args={[0.028, 0.06, height, 10]} />
        <meshStandardMaterial {...WOOD_SPAR} />
      </mesh>
      {/* Top platform + gilded truck */}
      <mesh position={[0, base + height * 0.7, 0]}>
        <cylinderGeometry args={[0.12, 0.12, 0.03, 12]} />
        <meshStandardMaterial {...WOOD_SPAR} />
      </mesh>
      <mesh position={[0, base + height, 0]}>
        <sphereGeometry args={[0.045, 8, 8]} />
        <meshStandardMaterial {...GOLD} />
      </mesh>

      {/* Lower course: yard + sail */}
      <mesh position={[0, lowYardY, 0]} rotation={[0, 0, Math.PI / 2]}>
        <cylinderGeometry args={[0.022, 0.022, lowerW + 0.24, 8]} />
        <meshStandardMaterial {...WOOD_SPAR} />
      </mesh>
      <mesh ref={lowSail} position={[0, lowSailY, 0]} geometry={geoms.low} castShadow>
        <meshStandardMaterial {...SAIL} />
      </mesh>

      {/* Topsail: yard + sail */}
      <mesh position={[0, upYardY, 0]} rotation={[0, 0, Math.PI / 2]}>
        <cylinderGeometry args={[0.018, 0.018, upperW + 0.18, 8]} />
        <meshStandardMaterial {...WOOD_SPAR} />
      </mesh>
      <mesh ref={upSail} position={[0, upSailY, 0]} geometry={geoms.up} castShadow>
        <meshStandardMaterial {...SAIL} />
      </mesh>

      {/* Shrouds */}
      {shrouds.map((r, i) => (
        <mesh key={i} position={r.position} rotation={r.rotation}>
          <cylinderGeometry args={[0.006, 0.006, r.len, 5]} />
          <meshStandardMaterial {...RIGGING} />
        </mesh>
      ))}
    </group>
  );
}

export default function Ship({
  scale = 1,
  volatility = 'gentle',
  zoomT = 0,
  reducedMotion = false,
}: ShipProps) {
  const hull = useRef<THREE.Group>(null);
  const foam = useRef<THREE.Group>(null);
  const flag = useRef<THREE.Group>(null);
  const lightRef = useRef<THREE.PointLight>(null);
  // Smoothed motion state so the vessel eases onto the swell instead of snapping.
  const motion = useRef({ y: 0.15, pitch: 0, roll: 0, foamY: 0 });

  // Keep the SOLID hull on top of the always-on-top chart overlays (the wake +
  // MA lines render transparent with depthTest disabled at renderOrder 6-10, so
  // an opaque ship would draw first and be painted over). We push every hull mesh
  // into the transparent pass (transparent=true, opacity stays 1 → still looks
  // solid) with a high renderOrder so it draws AFTER the lines, while KEEPING
  // depthTest + depthWrite so the hull still self-occludes correctly and is still
  // occluded by near wave crests — the ship keeps sitting IN the water. Net stack:
  // ship → chart lines → ocean weather → ocean base.
  useLayoutEffect(() => {
    const g = hull.current;
    if (!g) return;
    g.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (!mesh.isMesh) return;
      mesh.renderOrder = SHIP_RENDER_ORDER;
      const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      mats.forEach((m) => {
        m.transparent = true;
        m.depthWrite = true;
        m.depthTest = true;
        m.needsUpdate = true;
      });
    });
  }, []);

  // Hull shape (top-down outline in XZ, extruded then laid flat). Fuller,
  // rounded age-of-sail hull with a raked, pointed bow.
  const hullGeom = useMemo(() => {
    const shape = new THREE.Shape();
    const L = 2.05; // half-length
    const W = 0.62;
    shape.moveTo(-W * 0.86, -L * 0.98); // square-ish stern (transom)
    shape.lineTo(W * 0.86, -L * 0.98);
    shape.quadraticCurveTo(W, -L * 0.2, W * 0.92, L * 0.35);
    shape.quadraticCurveTo(W * 0.7, L * 0.82, W * 0.28, L * 0.98);
    shape.quadraticCurveTo(W * 0.12, L * 1.06, 0, L * 1.12); // pointed bow
    shape.quadraticCurveTo(-W * 0.12, L * 1.06, -W * 0.28, L * 0.98);
    shape.quadraticCurveTo(-W * 0.7, L * 0.82, -W * 0.92, L * 0.35);
    shape.quadraticCurveTo(-W, -L * 0.2, -W * 0.86, -L * 0.98);
    const geo = new THREE.ExtrudeGeometry(shape, {
      depth: 0.62,
      bevelEnabled: true,
      bevelSegments: 3,
      bevelSize: 0.08,
      bevelThickness: 0.08,
      steps: 1,
      curveSegments: 18,
    });
    geo.rotateX(-Math.PI / 2);
    geo.translate(0, -0.5, 0);
    return geo;
  }, []);

  // Jib / staysail geometries on the bowsprit forestays.
  const jibGeoms = useMemo(
    () => [
      triGeom([0, 2.28, 1.2], [0, 0.62, 2.95], [0, 0.78, 1.72]),
      triGeom([0, 1.72, 1.28], [0, 0.66, 2.4], [0, 0.72, 1.5]),
    ],
    [],
  );

  // Gun-port positions (Nelson chequer) along each beam.
  const gunPorts = useMemo(() => [-1.35, -0.95, -0.55, -0.15, 0.25, 0.65, 1.05], []);

  // Forestays linking mastheads and bowsprit.
  const stays = useMemo(() => {
    const segs: Array<[[number, number, number], [number, number, number]]> = [
      [[0, 2.32, 1.15], [0, 2.6, -0.1]],
      [[0, 2.32, 1.15], [0, 0.62, 2.95]],
      [[0, 2.6, -0.1], [0, 2.2, -1.2]],
    ];
    return segs.map(([a, b]) => riggingProps(new THREE.Vector3(...a), new THREE.Vector3(...b)));
  }, []);

  // The hull sits slightly into the water; this draft offset is added on top of
  // the sampled wave height so the waterline rides the surface.
  const DRAFT = 0.12;

  // Wake / spray intensity from the sea state; fades out toward the flat chart.
  const wakeInten = volatilityIntensity(volatility);
  const fxFade = Math.max(0, 1 - zoomT / 0.85);

  useFrame((state, delta) => {
    if (!hull.current) return;
    const t = reducedMotion ? 0 : state.clock.elapsedTime;

    // Reproduce the exact uniforms the ocean shader uses this frame so we
    // sample the same surface the GPU is displacing.
    const volUniform = volatilityIntensity(volatility) * (1 - zoomT * 0.92);
    const flatten = zoomT;

    const surf = sampleOceanSurface(0, 0, t, volUniform, flatten);

    const tiltGain = 0.6 * (1 - flatten);
    const targetY = DRAFT + surf.y;
    const targetPitch = surf.pitch * tiltGain;
    // Bow faces -Z (group flipped PI about Y); negate roll so the hull leans
    // into the wave correctly in that frame.
    const targetRoll = -surf.roll * tiltGain;

    const k = reducedMotion ? 1 : 1 - Math.exp(-delta * 9);
    motion.current.y += (targetY - motion.current.y) * k;
    motion.current.pitch += (targetPitch - motion.current.pitch) * k;
    motion.current.roll += (targetRoll - motion.current.roll) * k;
    motion.current.foamY += (surf.y - motion.current.foamY) * k;

    hull.current.position.y = motion.current.y;
    hull.current.rotation.x = motion.current.pitch;
    hull.current.rotation.z = motion.current.roll;

    if (foam.current) foam.current.position.y = motion.current.foamY;

    // Ensign flutters in the wind.
    if (flag.current) {
      flag.current.rotation.y = Math.sin(t * 3.2) * 0.28 + 0.1;
      flag.current.scale.x = 1 + Math.sin(t * 4.1) * 0.06;
    }

    // Stern lantern flicker.
    if (lightRef.current) lightRef.current.intensity = 1.5 + Math.sin(t * 5) * 0.25;
  });

  return (
    <group position={[0, 0, 0]}>
      {/* Wake + spray — lie flat on the water (track only surface height), so
          they stay pinned to the sea even as the hull bobs/pitches. The foam
          group is flipped PI about Y so local +Z points to the bow (world -Z). */}
      <group ref={foam} scale={scale} rotation={[0, Math.PI, 0]}>
        <BowWake intensity={wakeInten} fade={fxFade} reducedMotion={reducedMotion} />
        <Spray intensity={wakeInten} fade={fxFade} reducedMotion={reducedMotion} />
      </group>

      {/* Hull group — bobs / pitches / rolls with the swell. Bow faces -Z. */}
      <group ref={hull} scale={scale} position={[0, 0.15, 0]} rotation={[0, Math.PI, 0]}>
        {/* Planked wooden hull */}
        <mesh geometry={hullGeom} castShadow receiveShadow>
          <meshPhysicalMaterial
            color="#5b3a22"
            emissive="#160c05"
            emissiveIntensity={0.12}
            roughness={0.66}
            metalness={0.06}
            clearcoat={0.28}
            clearcoatRoughness={0.55}
            envMapIntensity={0.95}
          />
        </mesh>

        {/* Black waterline wale */}
        <mesh position={[0, -0.02, 0]}>
          <boxGeometry args={[1.3, 0.08, 3.9]} />
          <meshStandardMaterial color="#120d09" roughness={0.55} metalness={0.15} envMapIntensity={0.7} />
        </mesh>

        {/* Gun-port bands (ochre stripes) + black gun ports — Nelson chequer */}
        {[0.66, -0.66].map((sx) => (
          <group key={sx}>
            <mesh position={[sx, 0.1, -0.1]}>
              <boxGeometry args={[0.04, 0.14, 3.1]} />
              <meshStandardMaterial color="#d8a53a" roughness={0.6} metalness={0.08} envMapIntensity={0.8} />
            </mesh>
            {gunPorts.map((pz) => (
              <mesh key={pz} position={[sx + (sx > 0 ? 0.012 : -0.012), 0.1, pz]}>
                <boxGeometry args={[0.03, 0.09, 0.09]} />
                <meshStandardMaterial color="#0c0906" roughness={0.7} />
              </mesh>
            ))}
          </group>
        ))}

        {/* Upper ochre sheer strake */}
        {[0.63, -0.63].map((sx) => (
          <mesh key={sx} position={[sx, 0.26, -0.1]}>
            <boxGeometry args={[0.03, 0.06, 3.0]} />
            <meshStandardMaterial color="#d8a53a" roughness={0.6} metalness={0.08} envMapIntensity={0.8} />
          </mesh>
        ))}

        {/* Main deck */}
        <mesh position={[0, 0.2, 0.1]}>
          <boxGeometry args={[1.02, 0.06, 3.0]} />
          <meshStandardMaterial {...WOOD_DECK} />
        </mesh>

        {/* Bulwark rails (port + starboard) */}
        {[0.5, -0.5].map((sx) => (
          <mesh key={sx} position={[sx, 0.3, 0.0]}>
            <boxGeometry args={[0.04, 0.1, 3.0]} />
            <meshStandardMaterial {...WOOD_TRIM} />
          </mesh>
        ))}

        {/* ---- Raised stern castle (quarterdeck / poop) ---- */}
        <mesh position={[0, 0.42, -1.4]}>
          <boxGeometry args={[1.0, 0.4, 0.95]} />
          <meshStandardMaterial {...WOOD_TRIM} />
        </mesh>
        <mesh position={[0, 0.64, -1.4]}>
          <boxGeometry args={[1.02, 0.05, 0.98]} />
          <meshStandardMaterial {...WOOD_DECK} />
        </mesh>
        {/* Gold gallery frame on the transom (stern faces the camera) */}
        <mesh position={[0, 0.42, -1.9]}>
          <boxGeometry args={[0.92, 0.34, 0.04]} />
          <meshStandardMaterial {...GOLD} />
        </mesh>
        {/* Stern gallery windows (warm, lit) */}
        <mesh position={[0, 0.42, -1.915]}>
          <boxGeometry args={[0.8, 0.22, 0.03]} />
          <meshStandardMaterial color="#ffbf73" emissive="#ffb066" emissiveIntensity={1.1} roughness={0.25} />
        </mesh>
        {/* Window mullions */}
        {[-0.28, -0.14, 0, 0.14, 0.28].map((mx) => (
          <mesh key={mx} position={[mx, 0.42, -1.925]}>
            <boxGeometry args={[0.02, 0.24, 0.02]} />
            <meshStandardMaterial {...GOLD} />
          </mesh>
        ))}
        {/* Stern lantern */}
        <mesh position={[0, 0.78, -1.92]}>
          <cylinderGeometry args={[0.05, 0.06, 0.14, 8]} />
          <meshStandardMaterial color="#ffcf7a" emissive="#ffb84d" emissiveIntensity={2.6} roughness={0.3} />
        </mesh>
        <mesh position={[0, 0.87, -1.92]}>
          <coneGeometry args={[0.06, 0.06, 8]} />
          <meshStandardMaterial {...GOLD} />
        </mesh>
        <pointLight ref={lightRef} position={[0, 0.8, -1.9]} color="#ffca6e" intensity={1.5} distance={9} decay={2} />

        {/* ---- Bow: forecastle, bowsprit, figurehead, jibs ---- */}
        <mesh position={[0, 0.34, 1.35]}>
          <boxGeometry args={[0.86, 0.22, 0.6]} />
          <meshStandardMaterial {...WOOD_TRIM} />
        </mesh>
        {/* Bowsprit */}
        <mesh position={[0, 0.52, 2.45]} rotation={[1.29, 0, 0]}>
          <cylinderGeometry args={[0.028, 0.045, 1.35, 8]} />
          <meshStandardMaterial {...WOOD_SPAR} />
        </mesh>
        {/* Figurehead (gilded) */}
        <mesh position={[0, 0.28, 2.0]}>
          <sphereGeometry args={[0.09, 10, 10]} />
          <meshStandardMaterial {...GOLD} />
        </mesh>
        {/* Jibs / staysails on the bowsprit forestays */}
        {jibGeoms.map((g, i) => (
          <mesh key={i} geometry={g} castShadow>
            <meshStandardMaterial {...SAIL} />
          </mesh>
        ))}

        {/* ---- Three masts, fore → main → mizzen ---- */}
        <MastRig z={1.15} height={2.15} lowerW={1.45} upperW={1.1} reducedMotion={reducedMotion} />
        <MastRig z={-0.1} height={2.7} lowerW={1.75} upperW={1.32} reducedMotion={reducedMotion} />
        <MastRig z={-1.2} height={1.85} lowerW={1.2} upperW={0.92} reducedMotion={reducedMotion} />

        {/* Spanker (fore-aft sail) abaft the mizzen */}
        <mesh position={[0, 0.95, -1.7]} rotation={[0, Math.PI / 2, 0]}>
          <planeGeometry args={[0.85, 1.0]} />
          <meshStandardMaterial {...SAIL} />
        </mesh>

        {/* Forestays (standing rigging) */}
        {stays.map((r, i) => (
          <mesh key={i} position={r.position} rotation={r.rotation}>
            <cylinderGeometry args={[0.006, 0.006, r.len, 5]} />
            <meshStandardMaterial {...RIGGING} />
          </mesh>
        ))}

        {/* Ensign at the mainmast head */}
        <group ref={flag} position={[0, 2.92, -0.1]}>
          <mesh position={[0.14, 0, 0]}>
            <planeGeometry args={[0.28, 0.16]} />
            <meshStandardMaterial color="#c62828" emissive="#3a0a0a" emissiveIntensity={0.2} side={THREE.DoubleSide} roughness={0.8} />
          </mesh>
        </group>
      </group>
    </group>
  );
}
