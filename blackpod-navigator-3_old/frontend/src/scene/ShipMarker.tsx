import { useFrame } from '@react-three/fiber';
import { useRef } from 'react';
import * as THREE from 'three';

interface ShipMarkerProps {
  zoomT: number;
}

/**
 * Yellow halo / pulse ring on the water around the ship.
 * Helps the user *find* the ship at any zoom level — particularly at top-down
 * where the ship is small relative to the chart span.
 */
export default function ShipMarker({ zoomT }: ShipMarkerProps) {
  const ring1 = useRef<THREE.Mesh>(null);
  const ring2 = useRef<THREE.Mesh>(null);
  const mat1 = useRef<THREE.MeshBasicMaterial>(null);
  const mat2 = useRef<THREE.MeshBasicMaterial>(null);

  // Pulse amplitude shrinks as we zoom out so the ring stays contained
  // — at top-down we want a tight, bright marker, not a huge expanding halo.
  const pulseAmp = Math.max(0.18, 0.6 - zoomT * 0.45);

  useFrame((state) => {
    const t = state.clock.elapsedTime;
    if (ring1.current && mat1.current) {
      const frac = (t * 0.5) % 1.0;
      ring1.current.scale.setScalar(1 + frac * pulseAmp);
      mat1.current.opacity = Math.max(0, 0.7 - frac * 0.7) * (0.5 + zoomT * 0.5);
    }
    if (ring2.current && mat2.current) {
      const frac = (t * 0.5 + 0.5) % 1.0;
      ring2.current.scale.setScalar(1 + frac * pulseAmp);
      mat2.current.opacity = Math.max(0, 0.55 - frac * 0.55) * (0.5 + zoomT * 0.5);
    }
  });

  // Scale base radius with zoomT — bigger marker when zoomed out so the boat
  // is always findable. Curve tuned so HIGH (zoomT≈0.65) gives r≈18, CHART r≈40.
  const baseR = 1.6 + Math.pow(zoomT, 1.4) * 38;

  // Solid inner dot — guarantees the boat's location is always visible as a
  // yellow marker, even at extreme top-down where the ship mesh is tiny.
  const dotR = 0.5 + Math.pow(zoomT, 1.5) * 13;
  const dotOpacity = 0.0 + Math.pow(zoomT, 1.4) * 0.95;

  return (
    <group position={[0, 0.12, 0]}>
      <mesh ref={ring1} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[baseR * 0.85, baseR, 64]} />
        <meshBasicMaterial
          ref={mat1}
          color="#facc15"
          transparent
          opacity={0.5}
          toneMapped={false}
          depthWrite={false}
          side={THREE.DoubleSide}
        />
      </mesh>
      <mesh ref={ring2} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[baseR * 0.85, baseR, 64]} />
        <meshBasicMaterial
          ref={mat2}
          color="#facc15"
          transparent
          opacity={0.4}
          toneMapped={false}
          depthWrite={false}
          side={THREE.DoubleSide}
        />
      </mesh>
      {/* Solid yellow center dot — only visible at higher zoom */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.05, 0]}>
        <circleGeometry args={[dotR, 32]} />
        <meshBasicMaterial
          color="#facc15"
          transparent
          opacity={dotOpacity}
          toneMapped={false}
          depthWrite={false}
          side={THREE.DoubleSide}
        />
      </mesh>
    </group>
  );
}