import { shaderMaterial } from '@react-three/drei';
import { extend, useFrame } from '@react-three/fiber';
import { useMemo, useRef } from 'react';
import * as THREE from 'three';
import type { Volatility } from '../types';
import { volatilityIntensity } from './oceanHeight';

// drei's shaderMaterial: returns a class extending THREE.ShaderMaterial.
const OceanMat = shaderMaterial(
  {
    uTime: 0,
    uVolatility: 0.2,
    uFlatten: 0,
    uColorDeep: new THREE.Color('#03101f'),
    uColorMid: new THREE.Color('#0a1e34'),
    uColorHorizon: new THREE.Color('#1c3552'),
    uColorWarm: new THREE.Color('#7a4520'),
    uGridColor: new THREE.Color('#5a6878'),
  },
  // vertex
  /* glsl */ `
    uniform float uTime;
    uniform float uVolatility;
    uniform float uFlatten;
    varying vec3 vWorldPos;
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

    void main() {
      vec3 p = position;
      vec4 wp = modelMatrix * vec4(p, 1.0);
      float wave = 0.0;
      wave += sin(wp.x * 0.05 + uTime * 0.6) * 0.6;
      wave += sin(wp.z * 0.04 + uTime * 0.5) * 0.5;
      wave += noise(wp.xz * 0.12 + uTime * 0.4) * 1.2;
      wave += noise(wp.xz * 0.30 - uTime * 0.3) * 0.6;
      float vol = uVolatility * (1.0 - uFlatten);
      wave *= mix(0.05, 1.6, vol);
      p.y += wave;
      vWaveHeight = wave;
      vWorldPos = (modelMatrix * vec4(p, 1.0)).xyz;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
    }
  `,
  // fragment
  /* glsl */ `
    uniform float uFlatten;
    uniform vec3 uColorDeep;
    uniform vec3 uColorMid;
    uniform vec3 uColorHorizon;
    uniform vec3 uColorWarm;
    uniform vec3 uGridColor;
    varying vec3 vWorldPos;
    varying float vWaveHeight;

    void main() {
      vec3 wp = vWorldPos;
      float dist = length(wp.xz);
      float horizonFactor = clamp(wp.z / 1600.0, 0.0, 1.0);
      vec3 base = mix(uColorDeep, uColorMid, smoothstep(0.0, 0.45, horizonFactor));
      base = mix(base, uColorHorizon, smoothstep(0.5, 0.95, horizonFactor));
      // Sun reflection band — wide horizon glow plus a narrow shimmer pillar.
      float sunGlow = exp(-pow((wp.x) / 240.0, 2.0)) * smoothstep(0.74, 1.0, horizonFactor);
      base += uColorWarm * sunGlow * 0.5;
      // Vertical shimmer column from horizon toward camera
      float shimmer = exp(-pow(wp.x / 60.0, 2.0)) * smoothstep(0.0, 0.95, horizonFactor);
      shimmer *= 0.5 + 0.5 * sin(wp.z * 0.15 + vWaveHeight * 4.0);
      base += vec3(1.0, 0.55, 0.25) * shimmer * 0.18 * (1.0 - uFlatten);

      float spacing = 50.0;
      float lineW = 0.7;
      float dx = abs(fract(wp.x / spacing - 0.5) - 0.5) * spacing;
      float lineX = 1.0 - smoothstep(0.0, lineW, dx);
      float dashX = step(fract(wp.z / 16.0), 0.55);
      float dz = abs(fract(wp.z / spacing - 0.5) - 0.5) * spacing;
      float lineZ = 1.0 - smoothstep(0.0, lineW, dz);
      float dashZ = step(fract(wp.x / 16.0), 0.55);
      float gridMask = max(lineX * dashX, lineZ * dashZ);
      float gridFade = smoothstep(8.0, 60.0, dist) * (1.0 - smoothstep(1200.0, 1800.0, dist));
      float gridStrength = mix(0.10, 0.55, uFlatten);
      base = mix(base, mix(base, uGridColor, 0.85), gridMask * gridFade * gridStrength);

      float specMask = smoothstep(0.4, 1.4, vWaveHeight) * (1.0 - uFlatten);
      base += vec3(0.85, 0.78, 0.6) * specMask * 0.35;
      float foamMask = smoothstep(1.0, 2.2, vWaveHeight) * (1.0 - uFlatten);
      base += vec3(1.0) * foamMask * 0.55;

      float haze = smoothstep(400.0, 1700.0, dist) * (1.0 - uFlatten * 0.85);
      base = mix(base, vec3(0.07, 0.11, 0.19), haze * 0.35);

      gl_FragColor = vec4(base, 1.0);
    }
  `,
);

extend({ OceanMat });

interface OceanProps {
  volatility: Volatility;
  zoomT: number;
}

export default function Ocean({ volatility, zoomT }: OceanProps) {
  const matRef = useRef<THREE.ShaderMaterial & { uTime: number; uVolatility: number; uFlatten: number }>(null!);

  // Single source of truth shared with the ship's CPU wave sampling.
  const volIntensity = useMemo(() => volatilityIntensity(volatility), [volatility]);

  const geom = useMemo(() => {
    const g = new THREE.PlaneGeometry(2400, 4000, 220, 360);
    g.rotateX(-Math.PI / 2);
    return g;
  }, []);

  useFrame((_, delta) => {
    const m = matRef.current;
    if (!m) return;
    m.uTime += delta;
    m.uVolatility = volIntensity * (1 - zoomT * 0.92);
    m.uFlatten = zoomT;
  });

  return (
    <mesh geometry={geom} position={[0, 0, 1500]}>
      {/* @ts-expect-error custom material element from drei shaderMaterial */}
      <oceanMat ref={matRef} attach="material" />
    </mesh>
  );
}