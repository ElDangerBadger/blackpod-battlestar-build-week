import { shaderMaterial } from "@react-three/drei";
import { extend, useFrame } from "@react-three/fiber";
import { useEffect, useRef } from "react";
import * as THREE from "three";

const SunDiscMaterial = shaderMaterial(
  {
    uColorCore: new THREE.Color("#ffe1a8"),
    uColorEdge: new THREE.Color("#ff7e34"),
    uOpacity: 1,
  },
  /* glsl */ `
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,
  /* glsl */ `
    uniform vec3 uColorCore;
    uniform vec3 uColorEdge;
    uniform float uOpacity;
    varying vec2 vUv;
    void main() {
      float radius = length(vUv - 0.5) * 2.0;
      float core = smoothstep(0.28, 0.0, radius);
      float glow = pow(clamp(1.0 - radius, 0.0, 1.0), 3.0);
      vec3 color = mix(uColorEdge, uColorCore, max(core, glow * 0.5));
      float alpha = clamp(core + glow * 0.6, 0.0, 1.0) * uOpacity;
      gl_FragColor = vec4(color, alpha);
    }
  `,
);

extend({ SunDiscMaterial });

type SunDiscShaderMaterial = THREE.ShaderMaterial & { uOpacity: number };

export type SunDiscProps = Readonly<{
  position: THREE.Vector3;
  opacity: number;
  size?: number;
  onReady?: (mesh: THREE.Mesh | null) => void;
  /** Accepted for a uniform scene API; billboarding itself is not animation. */
  reducedMotion?: boolean;
}>;

/**
 * Camera-facing dusk sun. Billboarding follows the camera but has no autonomous
 * animation, so reduced-motion handling remains with the camera and scene.
 */
export function SunDisc({
  position,
  opacity,
  size = 360,
  onReady,
}: SunDiscProps) {
  const materialRef = useRef<SunDiscShaderMaterial>(null);
  const meshRef = useRef<THREE.Mesh>(null);

  useEffect(() => {
    if (materialRef.current) materialRef.current.uOpacity = opacity;
  }, [opacity]);

  useFrame(({ camera }) => {
    meshRef.current?.quaternion.copy(camera.quaternion);
  });

  return (
    <mesh
      ref={(mesh) => {
        meshRef.current = mesh;
        onReady?.(mesh);
      }}
      position={position}
    >
      <planeGeometry args={[size, size]} />
      {/* @ts-expect-error registered drei shader material element */}
      <sunDiscMaterial
        ref={materialRef}
        attach="material"
        transparent
        depthWrite={false}
        depthTest
        toneMapped={false}
        blending={THREE.NormalBlending}
      />
    </mesh>
  );
}

export default SunDisc;
