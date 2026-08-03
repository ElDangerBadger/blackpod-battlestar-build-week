import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import * as THREE from "three";

const DEFAULT_SIZE = [4.4, 6.6] as const;

const VERTEX_SHADER = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const FRAGMENT_SHADER = /* glsl */ `
  precision highp float;
  uniform float uTime;
  uniform float uIntensity;
  uniform float uFade;
  varying vec2 vUv;

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
  float fbm(vec2 p) {
    float value = 0.0;
    float amplitude = 0.5;
    for (int i = 0; i < 4; i++) {
      value += amplitude * noise(p);
      p *= 2.02;
      amplitude *= 0.5;
    }
    return value;
  }

  void main() {
    float across = vUv.x * 2.0 - 1.0;
    float along = vUv.y * 2.0 - 1.0;
    float amplitude = mix(0.3, 1.0, clamp(uIntensity, 0.0, 1.0));
    float bowPosition = 0.55;
    vec2 field = vec2(across * 2.4, along * 2.2 - uTime * 0.8);
    float turbulence = fbm(field * 1.4) * 0.7 + fbm(field * 0.6 + 5.0) * 0.5;

    float hullDistance = length(vec2(across / 0.62, (along - 0.02) / 0.9));
    float halo = 1.0 - smoothstep(0.15, 1.15, hullDistance);
    float behind = smoothstep(0.55, -0.95, along);
    float wash = smoothstep(0.42, 0.95, turbulence) * behind;
    float bow = 1.0 - smoothstep(
      0.0,
      0.32,
      distance(vec2(across, along), vec2(0.0, bowPosition))
    );
    float arm = (
      1.0 - smoothstep(0.0, 0.42, abs(abs(across) - 0.30 * (bowPosition - along)))
    ) * behind;

    float foam = halo * 0.5 + wash * 0.85 + bow * 0.55 + arm * 0.22;
    foam *= 0.45 + 0.75 * turbulence;
    float edge = (1.0 - smoothstep(0.5, 1.0, abs(across)))
      * (1.0 - smoothstep(0.5, 1.0, abs(along)));
    float alpha = clamp(foam, 0.0, 1.0) * edge * amplitude * uFade;
    if (alpha < 0.004) discard;

    vec3 color = mix(
      vec3(0.72, 0.82, 0.94),
      vec3(1.0),
      clamp(foam, 0.0, 1.0) * 0.7
    );
    gl_FragColor = vec4(color, clamp(alpha, 0.0, 0.6));
  }
`;

export type BowWakeProps = Readonly<{
  intensity?: number;
  fade?: number;
  size?: readonly [width: number, length: number];
  reducedMotion?: boolean;
}>;

export function BowWake({
  intensity = 0.4,
  fade = 1,
  size = DEFAULT_SIZE,
  reducedMotion = false,
}: BowWakeProps) {
  const invalidate = useThree((state) => state.invalidate);
  const geometry = useMemo(() => {
    const value = new THREE.PlaneGeometry(size[0], size[1], 1, 1);
    value.rotateX(-Math.PI / 2);
    return value;
  }, [size[0], size[1]]);
  const material = useMemo(() => new THREE.ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uIntensity: { value: 0.4 },
      uFade: { value: 1 },
    },
    vertexShader: VERTEX_SHADER,
    fragmentShader: FRAGMENT_SHADER,
    transparent: true,
    depthWrite: false,
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
    <mesh geometry={geometry} position={[0, 0.05, -0.2]}>
      <primitive object={material} attach="material" />
    </mesh>
  );
}

export default BowWake;
