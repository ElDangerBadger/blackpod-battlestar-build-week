import { useFrame } from "@react-three/fiber";
import { useRef } from "react";
import * as THREE from "three";

export type ShipMarkerProps = Readonly<{
  zoomT: number;
  reducedMotion?: boolean;
}>;

/** Yellow waterline marker that keeps the ship findable at chart scale. */
export function ShipMarker({
  zoomT,
  reducedMotion = false,
}: ShipMarkerProps) {
  const firstRing = useRef<THREE.Mesh>(null);
  const secondRing = useRef<THREE.Mesh>(null);
  const firstMaterial = useRef<THREE.MeshBasicMaterial>(null);
  const secondMaterial = useRef<THREE.MeshBasicMaterial>(null);
  const clampedZoom = Math.max(0, Math.min(1, zoomT));
  const pulseAmplitude = Math.max(0.18, 0.6 - clampedZoom * 0.45);

  useFrame((state) => {
    if (reducedMotion) {
      firstRing.current?.scale.setScalar(1);
      secondRing.current?.scale.setScalar(1);
      if (firstMaterial.current) {
        firstMaterial.current.opacity = 0.5 + clampedZoom * 0.25;
      }
      if (secondMaterial.current) {
        secondMaterial.current.opacity = 0.24 + clampedZoom * 0.2;
      }
      return;
    }

    const elapsed = state.clock.elapsedTime;
    if (firstRing.current && firstMaterial.current) {
      const phase = (elapsed * 0.5) % 1;
      firstRing.current.scale.setScalar(1 + phase * pulseAmplitude);
      firstMaterial.current.opacity =
        Math.max(0, 0.7 - phase * 0.7) * (0.5 + clampedZoom * 0.5);
    }
    if (secondRing.current && secondMaterial.current) {
      const phase = (elapsed * 0.5 + 0.5) % 1;
      secondRing.current.scale.setScalar(1 + phase * pulseAmplitude);
      secondMaterial.current.opacity =
        Math.max(0, 0.55 - phase * 0.55) * (0.5 + clampedZoom * 0.5);
    }
  });

  const baseRadius = 1.6 + Math.pow(clampedZoom, 1.4) * 38;
  const dotRadius = 0.5 + Math.pow(clampedZoom, 1.5) * 13;
  const dotOpacity = Math.pow(clampedZoom, 1.4) * 0.95;

  return (
    <group position={[0, 0.12, 0]}>
      <mesh ref={firstRing} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[baseRadius * 0.85, baseRadius, 64]} />
        <meshBasicMaterial
          ref={firstMaterial}
          color="#facc15"
          transparent
          opacity={reducedMotion ? 0.5 + clampedZoom * 0.25 : 0.5}
          toneMapped={false}
          depthWrite={false}
          side={THREE.DoubleSide}
        />
      </mesh>
      <mesh ref={secondRing} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[baseRadius * 0.85, baseRadius, 64]} />
        <meshBasicMaterial
          ref={secondMaterial}
          color="#facc15"
          transparent
          opacity={reducedMotion ? 0.24 + clampedZoom * 0.2 : 0.4}
          toneMapped={false}
          depthWrite={false}
          side={THREE.DoubleSide}
        />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.05, 0]}>
        <circleGeometry args={[dotRadius, 32]} />
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

export default ShipMarker;
