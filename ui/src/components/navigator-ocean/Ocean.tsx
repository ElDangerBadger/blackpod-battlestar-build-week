import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";

import type { NavigatorMarketSummary } from "../../contracts/cabinContext";

type OceanProps = Readonly<{
  volatility: NavigatorMarketSummary["volatility"];
  viewT: number;
  reducedMotion: boolean;
}>;

const VERTEX_SHADER = /* glsl */ `
  uniform float uTime;
  uniform float uVolatility;
  uniform float uFlatten;
  varying vec3 vWorld;
  varying float vWave;

  float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    float a = hash(i);
    float b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0));
    float d = hash(i + vec2(1.0, 1.0));
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(a, b, u.x) + (c - a) * u.y * (1.0 - u.x) + (d - b) * u.x * u.y;
  }

  void main() {
    vec3 p = position;
    vec4 world = modelMatrix * vec4(p, 1.0);
    float wave = sin(world.x * 0.055 + uTime * 0.52) * 0.55;
    wave += sin(world.z * 0.038 + uTime * 0.44) * 0.46;
    wave += noise(world.xz * 0.105 + uTime * 0.28) * 1.0;
    wave *= mix(0.04, 1.55, uVolatility * (1.0 - uFlatten));
    p.y += wave;
    vWave = wave;
    vWorld = (modelMatrix * vec4(p, 1.0)).xyz;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
  }
`;

const FRAGMENT_SHADER = /* glsl */ `
  uniform float uFlatten;
  varying vec3 vWorld;
  varying float vWave;

  void main() {
    float horizon = clamp((-vWorld.z) / 1800.0, 0.0, 1.0);
    vec3 deep = vec3(0.018, 0.070, 0.115);
    vec3 middle = vec3(0.040, 0.145, 0.205);
    vec3 dusk = vec3(0.145, 0.170, 0.205);
    vec3 color = mix(deep, middle, smoothstep(0.0, 0.62, horizon));
    color = mix(color, dusk, smoothstep(0.66, 1.0, horizon));

    float gridX = 1.0 - smoothstep(0.0, 0.8, abs(fract(vWorld.x / 50.0 - 0.5) - 0.5) * 50.0);
    float gridZ = 1.0 - smoothstep(0.0, 0.8, abs(fract(vWorld.z / 50.0 - 0.5) - 0.5) * 50.0);
    float grid = max(gridX, gridZ) * mix(0.05, 0.32, uFlatten);
    color = mix(color, vec3(0.35, 0.40, 0.44), grid);
    color += vec3(0.34, 0.30, 0.22) * smoothstep(0.75, 1.8, vWave) * (1.0 - uFlatten) * 0.24;
    gl_FragColor = vec4(color, 1.0);
  }
`;

function volatilityIntensity(volatility: NavigatorMarketSummary["volatility"]): number {
  switch (volatility) {
    case "glass": return 0.04;
    case "gentle": return 0.15;
    case "moderate": return 0.35;
    case "high": return 0.65;
    case "storm": return 1;
  }
}

export function Ocean({ volatility, viewT, reducedMotion }: OceanProps) {
  const invalidate = useThree((state) => state.invalidate);
  const materialRef = useRef<THREE.ShaderMaterial>(null);
  const geometry = useMemo(() => {
    const value = new THREE.PlaneGeometry(1900, 2600, 116, 156);
    value.rotateX(-Math.PI / 2);
    return value;
  }, []);
  const material = useMemo(() => new THREE.ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uVolatility: { value: volatilityIntensity(volatility) },
      uFlatten: { value: viewT },
    },
    vertexShader: VERTEX_SHADER,
    fragmentShader: FRAGMENT_SHADER,
  }), []);

  useEffect(() => {
    material.uniforms.uVolatility.value = volatilityIntensity(volatility);
    material.uniforms.uFlatten.value = viewT;
    invalidate();
  }, [invalidate, material, viewT, volatility]);

  useEffect(() => () => {
    geometry.dispose();
    material.dispose();
  }, [geometry, material]);

  useFrame((_, delta) => {
    if (reducedMotion) return;
    const current = materialRef.current;
    if (current) current.uniforms.uTime.value += Math.min(delta, 0.05);
  });

  return (
    <mesh geometry={geometry} position={[0, -0.08, -1080]}>
      <primitive ref={materialRef} object={material} attach="material" />
    </mesh>
  );
}
