import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import type { Volatility } from '../types';

interface OceanProps {
  volatility: Volatility;
  zoomT: number; // 0..1 — flatness multiplier (waves fade as zoomT → 1)
}

/**
 * Procedural ocean plane with:
 *  - dark blue gradient (deep near, lighter toward horizon)
 *  - faint dashed grid lines projected on the water
 *  - animated wave displacement driven by volatility
 *
 * Uses a custom shader for everything (single mesh, fast).
 */
export default function Ocean({ volatility, zoomT }: OceanProps) {
  const meshRef = useRef<THREE.Mesh>(null);
  const matRef = useRef<THREE.ShaderMaterial>(null);

  const volIntensity = useMemo(() => {
    switch (volatility) {
      case 'glass': return 0.02;
      case 'gentle': return 0.10;
      case 'moderate': return 0.25;
      case 'high': return 0.55;
      case 'storm': return 1.0;
      default: return 0.15;
    }
  }, [volatility]);

  const uniforms = useMemo(() => ({
    uTime: { value: 0 },
    uVolatility: { value: volIntensity },
    uFlatten: { value: 0 },
    uColorDeep: { value: new THREE.Color('#04101e') },
    uColorMid: { value: new THREE.Color('#0a1e34') },
    uColorHorizon: { value: new THREE.Color('#1a3450') },
    uColorWarm: { value: new THREE.Color('#7a4520') },
    uGridColor: { value: new THREE.Color('#5a6878') },
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }), []);

  // Geometry: high-segment plane along XZ (long, narrow)
  const geom = useMemo(() => {
    const g = new THREE.PlaneGeometry(2400, 4000, 220, 360);
    g.rotateX(-Math.PI / 2);
    return g;
  }, []);

  useFrame((_, delta) => {
    if (!matRef.current) return;
    matRef.current.uniforms.uTime.value += delta;
    matRef.current.uniforms.uVolatility.value = volIntensity * (1 - zoomT * 0.95);
    matRef.current.uniforms.uFlatten.value = zoomT;
  });

  return (
    <mesh ref={meshRef} geometry={geom} position={[0, 0, 1500]} receiveShadow>
      <shaderMaterial
        ref={matRef}
        uniforms={uniforms}
        vertexShader={vertexShader}
        fragmentShader={fragmentShader}
        transparent={false}
        fog
      />
    </mesh>
  );
}

const vertexShader = /* glsl */ `
  uniform float uTime;
  uniform float uVolatility;
  uniform float uFlatten;

  varying vec3 vWorldPos;
  varying float vWaveHeight;

  // Simple hash + noise (cheap & good enough)
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
    // Build a worldPos that doesn't have wave applied yet
    vec4 wp = modelMatrix * vec4(p, 1.0);
    float wave = 0.0;
    // Low-freq swells
    wave += sin(wp.x * 0.05 + uTime * 0.6) * 0.6;
    wave += sin(wp.z * 0.04 + uTime * 0.5) * 0.5;
    // Mid-freq chop
    wave += noise(wp.xz * 0.12 + uTime * 0.4) * 1.2;
    wave += noise(wp.xz * 0.30 - uTime * 0.3) * 0.6;
    // High-freq ripples
    wave += noise(wp.xz * 0.9 + uTime * 0.8) * 0.25;

    float vol = uVolatility * (1.0 - uFlatten);
    wave *= mix(0.05, 1.8, vol);

    p.y += wave;
    vWaveHeight = wave;

    vec4 mvPosition = modelViewMatrix * vec4(p, 1.0);
    vWorldPos = (modelMatrix * vec4(p, 1.0)).xyz;
    gl_Position = projectionMatrix * mvPosition;
  }
`;

const fragmentShader = /* glsl */ `
  uniform float uTime;
  uniform float uVolatility;
  uniform float uFlatten;
  uniform vec3 uColorDeep;
  uniform vec3 uColorMid;
  uniform vec3 uColorHorizon;
  uniform vec3 uColorWarm;
  uniform vec3 uGridColor;

  varying vec3 vWorldPos;
  varying float vWaveHeight;

  // ----- Grid (dashed) -----
  float dashedLine(float coord, float spacing, float lineW, float dash, float dashGap) {
    // grid line at multiples of spacing
    float d = abs(fract(coord / spacing - 0.5) - 0.5) * spacing;
    float lineMask = 1.0 - smoothstep(0.0, lineW, d);
    // dash along the OTHER axis — done by caller (we pass the perpendicular coord-mod)
    float dashMask = step(fract(coord / dash), dashGap);
    return lineMask * dashMask;
  }

  void main() {
    vec3 wp = vWorldPos;
    float dist = length(wp.xz);
    float horizonFactor = clamp(wp.z / 1800.0, 0.0, 1.0);
    // Base gradient: deep near camera, mid in middle, horizon glow far.
    vec3 base = mix(uColorDeep, uColorMid, smoothstep(0.0, 0.4, horizonFactor));
    base = mix(base, uColorHorizon, smoothstep(0.45, 0.95, horizonFactor));
    // Warm horizon glow near the sun (center top)
    float sunGlow = exp(-pow((wp.x) / 280.0, 2.0)) * smoothstep(0.6, 1.0, horizonFactor);
    base += uColorWarm * sunGlow * 0.55;

    // ----- Grid lines (faint, two axes) -----
    float spacing = 50.0;
    float lineW = 0.65;
    // X-lines (running along Z)
    float dx = abs(fract(wp.x / spacing - 0.5) - 0.5) * spacing;
    float lineX = 1.0 - smoothstep(0.0, lineW, dx);
    float dashX = step(fract(wp.z / 16.0), 0.55);
    // Z-lines (running along X)
    float dz = abs(fract(wp.z / spacing - 0.5) - 0.5) * spacing;
    float lineZ = 1.0 - smoothstep(0.0, lineW, dz);
    float dashZ = step(fract(wp.x / 16.0), 0.55);

    float gridMask = max(lineX * dashX, lineZ * dashZ);
    // Fade grid near camera and over very far distance
    float gridFade = smoothstep(8.0, 60.0, dist) * (1.0 - smoothstep(1200.0, 1900.0, dist));
    // Brighten grid as we approach top-down (chart mode)
    float gridStrength = mix(0.10, 0.55, uFlatten);
    base = mix(base, mix(base, uGridColor, 0.85), gridMask * gridFade * gridStrength);

    // ----- Wave specular highlights -----
    float specMask = smoothstep(0.4, 1.4, vWaveHeight) * (1.0 - uFlatten);
    base += vec3(0.85, 0.78, 0.6) * specMask * 0.35;
    // Foam on big waves
    float foamMask = smoothstep(1.0, 2.2, vWaveHeight) * (1.0 - uFlatten);
    base += vec3(1.0) * foamMask * 0.6;

    // Distance haze (cool blue-gray)
    float haze = smoothstep(180.0, 1600.0, dist) * (1.0 - uFlatten * 0.8);
    base = mix(base, vec3(0.08, 0.13, 0.21), haze * 0.5);

    gl_FragColor = vec4(base, 1.0);
  }
`;