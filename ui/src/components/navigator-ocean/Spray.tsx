import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import * as THREE from "three";

const DEFAULT_SEED = 0x4e415633;
const DEFAULT_ORIGIN = [0, 0.12, 2] as const;

const VERTEX_SHADER = /* glsl */ `
  attribute vec3 aSeed;
  attribute float aPhase;
  uniform float uTime;
  uniform float uIntensity;
  uniform float uPixel;
  varying float vAlpha;

  void main() {
    float rate = mix(0.35, 1.1, uIntensity);
    float lifeProgress = fract(uTime * rate + aPhase);
    float amplitude = mix(0.15, 1.0, uIntensity);
    float launch = mix(0.5, 2.4, uIntensity) * (0.6 + 0.4 * aSeed.y);
    float spread = mix(0.4, 1.7, uIntensity);
    float y = launch * lifeProgress
      - (launch + 0.6) * lifeProgress * lifeProgress;
    vec3 displaced = position + vec3(
      aSeed.x * spread * lifeProgress,
      max(y, -0.05),
      -abs(aSeed.z) * spread * lifeProgress
    );

    vec4 modelView = modelViewMatrix * vec4(displaced, 1.0);
    float sizeJitter = 0.6 + 0.8 * aSeed.y;
    gl_PointSize = (uPixel * sizeJitter * amplitude)
      * (1.0 - 0.5 * lifeProgress)
      / max(-modelView.z, 0.1);
    gl_Position = projectionMatrix * modelView;
    float life = smoothstep(0.0, 0.12, lifeProgress)
      * (1.0 - smoothstep(0.55, 1.0, lifeProgress));
    vAlpha = life * amplitude;
  }
`;

const FRAGMENT_SHADER = /* glsl */ `
  precision highp float;
  uniform float uFade;
  varying float vAlpha;
  void main() {
    float distanceFromCenter = length(gl_PointCoord - 0.5);
    float alpha = smoothstep(0.5, 0.08, distanceFromCenter) * vAlpha * uFade;
    if (alpha < 0.01) discard;
    gl_FragColor = vec4(vec3(0.86, 0.92, 1.0), alpha * 0.8);
  }
`;

function seededRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4_294_967_296;
  };
}

export type SprayParticleSeeds = Readonly<{
  seeds: Float32Array;
  phases: Float32Array;
}>;

/** Generate stable particle attributes for deterministic mission replay. */
export function createSprayParticleSeeds(
  count: number,
  seed = DEFAULT_SEED,
): SprayParticleSeeds {
  if (!Number.isInteger(count) || count < 0) {
    throw new RangeError("count must be a nonnegative integer");
  }
  if (!Number.isFinite(seed)) {
    throw new RangeError("seed must be finite");
  }

  const random = seededRandom(seed);
  const seeds = new Float32Array(count * 3);
  const phases = new Float32Array(count);
  for (let index = 0; index < count; index += 1) {
    seeds[index * 3] = (random() * 2 - 1) * 1;
    seeds[index * 3 + 1] = random();
    seeds[index * 3 + 2] = random();
    phases[index] = random();
  }
  return { seeds, phases };
}

export type SprayProps = Readonly<{
  intensity?: number;
  fade?: number;
  count?: number;
  origin?: readonly [x: number, y: number, z: number];
  seed?: number;
  reducedMotion?: boolean;
}>;

export function Spray({
  intensity = 0.3,
  fade = 1,
  count = 120,
  origin = DEFAULT_ORIGIN,
  seed = DEFAULT_SEED,
  reducedMotion = false,
}: SprayProps) {
  const invalidate = useThree((state) => state.invalidate);
  const geometry = useMemo(() => {
    const value = new THREE.BufferGeometry();
    const positions = new Float32Array(count * 3);
    for (let index = 0; index < count; index += 1) {
      positions[index * 3] = origin[0];
      positions[index * 3 + 1] = origin[1];
      positions[index * 3 + 2] = origin[2];
    }
    const particleSeeds = createSprayParticleSeeds(count, seed);
    value.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    value.setAttribute("aSeed", new THREE.BufferAttribute(particleSeeds.seeds, 3));
    value.setAttribute("aPhase", new THREE.BufferAttribute(particleSeeds.phases, 1));
    return value;
  }, [count, origin[0], origin[1], origin[2], seed]);
  const material = useMemo(() => new THREE.ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uIntensity: { value: 0.3 },
      uFade: { value: 1 },
      uPixel: { value: 240 },
    },
    vertexShader: VERTEX_SHADER,
    fragmentShader: FRAGMENT_SHADER,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    toneMapped: false,
  }), []);

  useEffect(() => {
    material.uniforms.uIntensity.value = intensity;
    material.uniforms.uFade.value = fade;
    invalidate();
  }, [fade, intensity, invalidate, material]);

  useEffect(() => () => {
    geometry.dispose();
    material.dispose();
  }, [geometry, material]);

  useFrame((_, delta) => {
    if (reducedMotion) return;
    material.uniforms.uTime.value += Math.min(delta, 0.05);
  });

  return (
    <points geometry={geometry}>
      <primitive object={material} attach="material" />
    </points>
  );
}

export default Spray;
