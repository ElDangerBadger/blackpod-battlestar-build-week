import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import * as THREE from "three";

import { SKY_GLSL } from "./skyGlsl";

const VERTEX_SHADER = /* glsl */ `
  varying vec3 vWorldPosition;
  void main() {
    vWorldPosition = position;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const FRAGMENT_SHADER = /* glsl */ `
  uniform float uTime;
  uniform float uZoomT;
  uniform vec3 uFlatColor;
  varying vec3 vWorldPosition;

  ${SKY_GLSL}

  void main() {
    vec3 direction = normalize(vWorldPosition);
    vec3 color = bpSkyColor(direction, uTime);
    color += vec3(0.85, 0.9, 1.0)
      * bpStars(direction, uTime)
      * (1.0 - uZoomT);
    color = mix(color, uFlatColor, smoothstep(0.7, 1.0, uZoomT));
    gl_FragColor = vec4(color, 1.0);
  }
`;

export type SkyProps = Readonly<{
  zoomT: number;
  reducedMotion?: boolean;
}>;

export function Sky({ zoomT, reducedMotion = false }: SkyProps) {
  const invalidate = useThree((state) => state.invalidate);
  const geometry = useMemo(() => new THREE.SphereGeometry(2400, 48, 32), []);
  const material = useMemo(() => new THREE.ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uZoomT: { value: 0 },
      uFlatColor: { value: new THREE.Color("#070b14") },
    },
    vertexShader: VERTEX_SHADER,
    fragmentShader: FRAGMENT_SHADER,
    side: THREE.BackSide,
    depthWrite: false,
  }), []);

  useEffect(() => {
    material.uniforms.uZoomT.value = zoomT;
    invalidate();
  }, [invalidate, material, zoomT]);

  useEffect(() => () => {
    geometry.dispose();
    material.dispose();
  }, [geometry, material]);

  useFrame((_, delta) => {
    if (reducedMotion) return;
    material.uniforms.uTime.value += Math.min(delta, 0.05);
  });

  return (
    <mesh geometry={geometry}>
      <primitive object={material} attach="material" />
    </mesh>
  );
}

export default Sky;
