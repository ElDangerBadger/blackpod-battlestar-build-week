import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import type { Volatility } from '../types';
import { sampleOceanSurface, volatilityIntensity } from './oceanHeight';

interface ShipProps {
  scale?: number;
  volatility?: Volatility;
  zoomT?: number;
}

/**
 * Procedural realistic-ish small vessel.
 * Hull: dark red, white deck, dark glass cabin, mast, navigation light.
 * Faces +Z (toward horizon / past wake direction is -Z, so ship moves toward +Z visually).
 *
 * Actually: in our coordinate system, the wake (history) extends along +Z (away from camera into horizon).
 * Camera sits at -Z looking toward +Z. So the ship's bow points along +Z (toward horizon).
 */
export default function Ship({ scale = 1, volatility = 'gentle', zoomT = 0 }: ShipProps) {
  const hull = useRef<THREE.Group>(null);
  const foam = useRef<THREE.Group>(null);
  const lightRef = useRef<THREE.PointLight>(null);
  // Smoothed motion state so the vessel eases onto the swell instead of snapping.
  const motion = useRef({ y: 0.15, pitch: 0, roll: 0, foamY: 0 });

  // Hull shape (top-down outline, in XZ then extruded along Y)
  const hullGeom = useMemo(() => {
    const shape = new THREE.Shape();
    // length along Z: 4 units, width along X: 1.3 units
    const L = 2;   // half-length
    const W = 0.65;
    shape.moveTo(-W, -L * 0.95);
    shape.lineTo(W, -L * 0.95);
    shape.quadraticCurveTo(W, L * 0.4, W * 0.55, L * 0.85);
    shape.quadraticCurveTo(W * 0.3, L, 0, L * 1.02);
    shape.quadraticCurveTo(-W * 0.3, L, -W * 0.55, L * 0.85);
    shape.quadraticCurveTo(-W, L * 0.4, -W, -L * 0.95);
    const geo = new THREE.ExtrudeGeometry(shape, {
      depth: 0.55,
      bevelEnabled: true,
      bevelSegments: 3,
      bevelSize: 0.07,
      bevelThickness: 0.07,
      steps: 1,
      curveSegments: 16,
    });
    geo.rotateX(-Math.PI / 2); // lay flat with hull below
    geo.translate(0, -0.45, 0);
    return geo;
  }, []);

  // The hull sits slightly into the water; this is the draft offset added on
  // top of the sampled wave height so the waterline trim rides the surface.
  const DRAFT = 0.12;

  useFrame((state, delta) => {
    if (!hull.current) return;
    const t = state.clock.elapsedTime;

    // Reproduce the exact uniforms the ocean shader uses this frame so we
    // sample the same surface the GPU is displacing.
    const volUniform = volatilityIntensity(volatility) * (1 - zoomT * 0.92);
    const flatten = zoomT;

    // Sample height + local slope at the ship's location (world origin).
    const surf = sampleOceanSurface(0, 0, t, volUniform, flatten);

    // Tilt eases off as we zoom to the flat top-down chart.
    const tiltGain = 0.6 * (1 - flatten);
    const targetY = DRAFT + surf.y;
    const targetPitch = surf.pitch * tiltGain;
    // Bow faces -Z (group is rotated PI about Y); negate roll so the hull
    // leans into the wave correctly in that flipped frame.
    const targetRoll = -surf.roll * tiltGain;

    // Critically-damped-ish smoothing toward the target so motion is buoyant,
    // not jittery, and frame-rate independent.
    const k = 1 - Math.exp(-delta * 9);
    motion.current.y += (targetY - motion.current.y) * k;
    motion.current.pitch += (targetPitch - motion.current.pitch) * k;
    motion.current.roll += (targetRoll - motion.current.roll) * k;
    // Foam tracks the bare water surface (no draft) so it lies on the water,
    // staying flat instead of lifting/tilting with the hull.
    motion.current.foamY += (surf.y - motion.current.foamY) * k;

    hull.current.position.y = motion.current.y;
    hull.current.rotation.x = motion.current.pitch;
    hull.current.rotation.z = motion.current.roll;

    if (foam.current) {
      foam.current.position.y = motion.current.foamY;
    }

    if (lightRef.current) {
      lightRef.current.intensity = 1.8 + Math.sin(t * 4) * 0.2;
    }
  });

  return (
    // Root anchor at the ship's location (world origin). The foam decals and the
    // hull are siblings so the hull can bob/pitch while the foam stays flat on
    // the water surface.
    <group position={[0, 0, 0]}>
      {/* Foam decals — lie flat on the water, track only the surface height. */}
      <group ref={foam} scale={scale} rotation={[0, Math.PI, 0]}>
        <mesh position={[0, 0.04, -0.3]} rotation={[-Math.PI / 2, 0, 0]}>
          <planeGeometry args={[3.5, 5.2]} />
          <meshBasicMaterial color="#dde9f4" transparent opacity={0.3} toneMapped={false} depthWrite={false} />
        </mesh>
        <mesh position={[0, 0.05, 0.9]} rotation={[-Math.PI / 2, 0, 0]}>
          <planeGeometry args={[2.5, 1.5]} />
          <meshBasicMaterial color="#ffffff" transparent opacity={0.4} toneMapped={false} depthWrite={false} />
        </mesh>
      </group>

      {/* Hull group — bobs vertically and pitches/rolls with the swell.
          Bow faces -Z (toward the horizon / wake direction). */}
      <group ref={hull} scale={scale} position={[0, 0.15, 0]} rotation={[0, Math.PI, 0]}>
      {/* Hull */}
      <mesh geometry={hullGeom} castShadow receiveShadow>
        <meshStandardMaterial
          color="#8a1c1c"
          emissive="#3a0a0a"
          emissiveIntensity={0.25}
          roughness={0.55}
          metalness={0.2}
        />
      </mesh>
      {/* Hull waterline trim */}
      <mesh position={[0, 0.02, 0]}>
        <boxGeometry args={[1.32, 0.04, 3.85]} />
        <meshStandardMaterial color="#1a1a1a" roughness={0.5} />
      </mesh>
      {/* Deck */}
      <mesh position={[0, 0.18, 0.1]}>
        <boxGeometry args={[1.1, 0.06, 3.0]} />
        <meshStandardMaterial color="#e8e6e0" roughness={0.7} />
      </mesh>
      {/* Forward cabin */}
      <mesh position={[0, 0.42, 0.3]}>
        <boxGeometry args={[0.8, 0.42, 1.1]} />
        <meshStandardMaterial color="#1a2230" roughness={0.3} metalness={0.4} />
      </mesh>
      {/* Cabin windows (emissive strip) */}
      <mesh position={[0, 0.5, 0.85]}>
        <boxGeometry args={[0.82, 0.14, 0.02]} />
        <meshStandardMaterial
          color="#ffb066"
          emissive="#ffb066"
          emissiveIntensity={0.9}
          roughness={0.2}
        />
      </mesh>
      <mesh position={[0.405, 0.5, 0.3]} rotation={[0, Math.PI / 2, 0]}>
        <boxGeometry args={[1.0, 0.14, 0.02]} />
        <meshStandardMaterial color="#ffb066" emissive="#ffb066" emissiveIntensity={0.7} />
      </mesh>
      <mesh position={[-0.405, 0.5, 0.3]} rotation={[0, Math.PI / 2, 0]}>
        <boxGeometry args={[1.0, 0.14, 0.02]} />
        <meshStandardMaterial color="#ffb066" emissive="#ffb066" emissiveIntensity={0.7} />
      </mesh>
      {/* Cabin roof */}
      <mesh position={[0, 0.66, 0.3]}>
        <boxGeometry args={[0.86, 0.05, 1.16]} />
        <meshStandardMaterial color="#c5c1b6" roughness={0.6} />
      </mesh>
      {/* Mast */}
      <mesh position={[0, 1.05, 0.0]}>
        <cylinderGeometry args={[0.025, 0.025, 0.85, 8]} />
        <meshStandardMaterial color="#2a2a2a" roughness={0.5} />
      </mesh>
      {/* Navigation light at top of mast */}
      <mesh position={[0, 1.5, 0]}>
        <sphereGeometry args={[0.06, 12, 12]} />
        <meshStandardMaterial
          color="#facc15"
          emissive="#facc15"
          emissiveIntensity={3.5}
        />
      </mesh>
      <pointLight
        ref={lightRef}
        position={[0, 1.5, 0]}
        color="#ffd35a"
        intensity={1.8}
        distance={12}
        decay={2}
      />
      {/* Bow rail */}
      <mesh position={[0, 0.32, 1.5]}>
        <boxGeometry args={[0.9, 0.02, 0.05]} />
        <meshStandardMaterial color="#cccccc" />
      </mesh>
      </group>
    </group>
  );
}