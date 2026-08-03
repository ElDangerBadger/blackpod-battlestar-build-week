import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import * as THREE from "three";

import { volatilityIntensity } from "./oceanHeight";
import { SKY_GLSL } from "./skyGlsl";
import type { NavigatorOceanVolatility } from "./types";

const VERTEX_SHADER = /* glsl */ `
  uniform float uTime;
  uniform float uVolatility;
  uniform float uFlatten;
  varying vec3 vWorldPosition;
  varying vec3 vWorldNormal;
  varying float vWaveHeight;

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

  float waveAt(vec2 position, float amplitude) {
    float wave = 0.0;
    wave += sin(position.x * 0.05 + uTime * 0.6) * 0.6;
    wave += sin(position.y * 0.04 + uTime * 0.5) * 0.5;
    wave += noise(position * 0.12 + uTime * 0.4) * 1.2;
    wave += noise(position * 0.30 - uTime * 0.3) * 0.6;
    return wave * amplitude;
  }

  void main() {
    vec3 displaced = position;
    vec4 world = modelMatrix * vec4(displaced, 1.0);
    float flatten = clamp(uFlatten, 0.0, 1.0);
    float volatility = uVolatility * (1.0 - flatten);
    float chartFade = 1.0 - smoothstep(0.92, 1.0, flatten);
    float amplitude = mix(0.05, 1.6, volatility) * chartFade;
    float height = waveAt(world.xz, amplitude);
    displaced.y += height;
    vWaveHeight = height;
    vWorldPosition = (modelMatrix * vec4(displaced, 1.0)).xyz;

    float epsilon = 9.0;
    float xPositive = waveAt(world.xz + vec2(epsilon, 0.0), amplitude);
    float xNegative = waveAt(world.xz - vec2(epsilon, 0.0), amplitude);
    float zPositive = waveAt(world.xz + vec2(0.0, epsilon), amplitude);
    float zNegative = waveAt(world.xz - vec2(0.0, epsilon), amplitude);
    vWorldNormal = normalize(vec3(
      -(xPositive - xNegative) / (2.0 * epsilon),
      1.0,
      -(zPositive - zNegative) / (2.0 * epsilon)
    ));
    gl_Position = projectionMatrix * modelViewMatrix * vec4(displaced, 1.0);
  }
`;

const FRAGMENT_SHADER = /* glsl */ `
  uniform float uTime;
  uniform float uFlatten;
  uniform vec3 uColorDeep;
  uniform vec3 uColorMiddle;
  uniform vec3 uColorHorizon;
  uniform vec3 uGridColor;
  varying vec3 vWorldPosition;
  varying vec3 vWorldNormal;
  varying float vWaveHeight;

  ${SKY_GLSL}

  void main() {
    vec3 world = vWorldPosition;
    float distanceFromOrigin = length(world.xz);
    float horizon = clamp(world.z / 1600.0, 0.0, 1.0);
    float effectFade = 1.0 - uFlatten;

    vec3 water = mix(uColorDeep, uColorMiddle, smoothstep(0.0, 0.45, horizon));
    water = mix(water, uColorHorizon, smoothstep(0.5, 0.95, horizon));
    vec3 normal = normalize(mix(vec3(0.0, 1.0, 0.0), vWorldNormal, effectFade));
    vec3 viewDirection = normalize(cameraPosition - world);
    float normalView = clamp(dot(normal, viewDirection), 0.0, 1.0);
    float fresnel = 0.02 + 0.55 * pow(1.0 - normalView, 5.0);
    vec3 reflectionDirection = reflect(-viewDirection, normal);
    reflectionDirection.y = abs(reflectionDirection.y);
    vec3 reflection = bpSkyColor(reflectionDirection, uTime) * 0.58;
    vec3 color = mix(water, reflection, fresnel * effectFade);

    vec3 sunDirection = bpSunDir();
    vec3 halfway = normalize(viewDirection + sunDirection);
    float normalHalfway = max(dot(normal, halfway), 0.0);
    float hotSpecular = pow(normalHalfway, 220.0);
    float wideSpecular = pow(normalHalfway, 28.0);
    color += vec3(1.0, 0.78, 0.5) * hotSpecular * 1.2 * effectFade;
    color += vec3(1.0, 0.66, 0.38) * wideSpecular * 0.30 * effectFade;

    vec2 sunAzimuth = normalize(sunDirection.xz);
    vec2 towardSurface = normalize(world.xz - cameraPosition.xz);
    float roadAlignment = pow(max(dot(towardSurface, sunAzimuth), 0.0), 6.0);
    color += vec3(1.0, 0.70, 0.42)
      * roadAlignment * wideSpecular * 0.5 * effectFade;

    float crest = smoothstep(0.55, 1.7, vWaveHeight);
    float slope = clamp(1.0 - normal.y, 0.0, 1.0);
    float face = smoothstep(0.015, 0.09, slope);
    float foam = (crest * 0.42 + face * crest * 0.55) * effectFade;
    color += vec3(0.86, 0.93, 1.0) * foam;

    float spacing = 50.0;
    float lineWidth = 0.7;
    float distanceX = abs(fract(world.x / spacing - 0.5) - 0.5) * spacing;
    float lineX = 1.0 - smoothstep(0.0, lineWidth, distanceX);
    float dashX = step(fract(world.z / 16.0), 0.55);
    float distanceZ = abs(fract(world.z / spacing - 0.5) - 0.5) * spacing;
    float lineZ = 1.0 - smoothstep(0.0, lineWidth, distanceZ);
    float dashZ = step(fract(world.x / 16.0), 0.55);
    float gridMask = max(lineX * dashX, lineZ * dashZ);
    float gridFade = smoothstep(8.0, 60.0, distanceFromOrigin)
      * (1.0 - smoothstep(1200.0, 1800.0, distanceFromOrigin));
    float gridStrength = mix(0.10, 0.42, smoothstep(0.0, 0.6, uFlatten))
      * (1.0 - smoothstep(0.62, 0.98, uFlatten));
    color = mix(color, mix(color, uGridColor, 0.85), gridMask * gridFade * gridStrength);

    float haze = smoothstep(650.0, 1800.0, distanceFromOrigin)
      * (1.0 - uFlatten * 0.85);
    color = mix(color, vec3(0.05, 0.09, 0.17), haze * 0.3);
    gl_FragColor = vec4(color, 1.0);
  }
`;

export type OceanProps = Readonly<{
  volatility: NavigatorOceanVolatility;
  zoomT: number;
  reducedMotion?: boolean;
}>;

export function Ocean({ volatility, zoomT, reducedMotion = false }: OceanProps) {
  const invalidate = useThree((state) => state.invalidate);
  const geometry = useMemo(() => {
    const value = new THREE.PlaneGeometry(2400, 4000, 320, 480);
    value.rotateX(-Math.PI / 2);
    return value;
  }, []);
  const material = useMemo(() => new THREE.ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uVolatility: { value: 0.2 },
      uFlatten: { value: 0 },
      uColorDeep: { value: new THREE.Color("#02090f") },
      uColorMiddle: { value: new THREE.Color("#071a2e") },
      uColorHorizon: { value: new THREE.Color("#16304c") },
      uGridColor: { value: new THREE.Color("#5a6878") },
    },
    vertexShader: VERTEX_SHADER,
    fragmentShader: FRAGMENT_SHADER,
  }), []);

  useEffect(() => {
    material.uniforms.uVolatility.value = volatilityIntensity(volatility) * (1 - zoomT * 0.92);
    material.uniforms.uFlatten.value = zoomT;
    invalidate();
  }, [invalidate, material, volatility, zoomT]);

  useEffect(() => () => {
    geometry.dispose();
    material.dispose();
  }, [geometry, material]);

  useFrame((_, delta) => {
    if (reducedMotion) return;
    material.uniforms.uTime.value += Math.min(delta, 0.05);
  });

  return (
    <mesh
      geometry={geometry}
      position={[0, 0, 1500]}
      visible={zoomT < 0.999}
    >
      <primitive object={material} attach="material" />
    </mesh>
  );
}

export default Ocean;
