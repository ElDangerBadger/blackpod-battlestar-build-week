import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";

type ShipProps = Readonly<{
  scale: number;
  bobIntensity: number;
  reducedMotion: boolean;
}>;

/** A procedural vessel adapted from the pinned standalone Navigator scene. */
export function Ship({ scale, bobIntensity, reducedMotion }: ShipProps) {
  const group = useRef<THREE.Group>(null);
  const hullGeometry = useMemo(() => {
    const shape = new THREE.Shape();
    const halfLength = 2;
    const halfWidth = 0.65;
    shape.moveTo(-halfWidth, -halfLength * 0.95);
    shape.lineTo(halfWidth, -halfLength * 0.95);
    shape.quadraticCurveTo(halfWidth, halfLength * 0.4, halfWidth * 0.55, halfLength * 0.85);
    shape.quadraticCurveTo(halfWidth * 0.3, halfLength, 0, halfLength * 1.02);
    shape.quadraticCurveTo(-halfWidth * 0.3, halfLength, -halfWidth * 0.55, halfLength * 0.85);
    shape.quadraticCurveTo(-halfWidth, halfLength * 0.4, -halfWidth, -halfLength * 0.95);
    const geometry = new THREE.ExtrudeGeometry(shape, {
      depth: 0.55,
      bevelEnabled: true,
      bevelSegments: 2,
      bevelSize: 0.07,
      bevelThickness: 0.07,
      steps: 1,
      curveSegments: 12,
    });
    geometry.rotateX(-Math.PI / 2);
    geometry.translate(0, -0.45, 0);
    return geometry;
  }, []);

  useFrame(({ clock }) => {
    if (reducedMotion || !group.current) return;
    const elapsed = clock.elapsedTime;
    group.current.position.y = 0.16 + Math.sin(elapsed * 1.1) * 0.06 * bobIntensity * scale;
    group.current.rotation.z = Math.sin(elapsed * 0.9) * 0.03 * bobIntensity;
    group.current.rotation.x = Math.sin(elapsed * 0.7 + 1.2) * 0.018 * bobIntensity;
  });

  return (
    <group ref={group} scale={scale} position={[0, 0.16, 0]} rotation={[0, Math.PI, 0]}>
      <mesh position={[0, -0.12, -0.3]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[3.5, 5.2]} />
        <meshBasicMaterial color="#dde9f4" transparent opacity={0.28} toneMapped={false} depthWrite={false} />
      </mesh>
      <mesh geometry={hullGeometry}>
        <meshStandardMaterial color="#8a1c1c" emissive="#3a0a0a" emissiveIntensity={0.25} roughness={0.55} metalness={0.2} />
      </mesh>
      <mesh position={[0, 0.18, 0.1]}>
        <boxGeometry args={[1.1, 0.06, 3]} />
        <meshStandardMaterial color="#e8e6e0" roughness={0.7} />
      </mesh>
      <mesh position={[0, 0.43, 0.3]}>
        <boxGeometry args={[0.8, 0.42, 1.1]} />
        <meshStandardMaterial color="#1a2230" roughness={0.3} metalness={0.4} />
      </mesh>
      <mesh position={[0, 0.51, 0.86]}>
        <boxGeometry args={[0.82, 0.14, 0.02]} />
        <meshStandardMaterial color="#ffb066" emissive="#ffb066" emissiveIntensity={0.85} />
      </mesh>
      <mesh position={[0, 0.67, 0.3]}>
        <boxGeometry args={[0.86, 0.05, 1.16]} />
        <meshStandardMaterial color="#c5c1b6" roughness={0.6} />
      </mesh>
      <mesh position={[0, 1.05, 0]}>
        <cylinderGeometry args={[0.025, 0.025, 0.85, 8]} />
        <meshStandardMaterial color="#252525" />
      </mesh>
      <mesh position={[0, 1.5, 0]}>
        <sphereGeometry args={[0.06, 10, 10]} />
        <meshStandardMaterial color="#facc15" emissive="#facc15" emissiveIntensity={3.2} />
      </mesh>
      <pointLight position={[0, 1.5, 0]} color="#ffd35a" intensity={1.7} distance={12} decay={2} />
    </group>
  );
}
