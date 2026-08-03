import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';

interface SkyProps {
  zoomT: number;
}

/**
 * Custom gradient sky dome — sunset/dawn cinematic:
 *  zenith deep slate → warm amber near horizon → orange sun glow center.
 *  Fades to flat dark as zoomT → 1 (top-down chart mode).
 */
export default function Sky({ zoomT }: SkyProps) {
  const matRef = useRef<THREE.ShaderMaterial>(null);
  const uniforms = useMemo(() => ({
    uTime: { value: 0 },
    uZoomT: { value: 0 },
    uColorZenith: { value: new THREE.Color('#040813') },
    uColorMid: { value: new THREE.Color('#0c1830') },
    uColorHorizon: { value: new THREE.Color('#3a2a1f') },
    uColorSun: { value: new THREE.Color('#e88a3c') },
    uColorFlat: { value: new THREE.Color('#070b14') },
  }), []);

  useFrame((_, delta) => {
    if (!matRef.current) return;
    matRef.current.uniforms.uTime.value += delta;
    matRef.current.uniforms.uZoomT.value = zoomT;
  });

  return (
    <mesh position={[0, 0, 0]} scale={[1, 1, 1]}>
      <sphereGeometry args={[2400, 32, 24]} />
      <shaderMaterial
        ref={matRef}
        uniforms={uniforms}
        vertexShader={vertexShader}
        fragmentShader={fragmentShader}
        side={THREE.BackSide}
        depthWrite={false}
      />
    </mesh>
  );
}

const vertexShader = /* glsl */ `
  varying vec3 vWorldPos;
  void main() {
    vWorldPos = position;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const fragmentShader = /* glsl */ `
  uniform float uTime;
  uniform float uZoomT;
  uniform vec3 uColorZenith;
  uniform vec3 uColorMid;
  uniform vec3 uColorHorizon;
  uniform vec3 uColorSun;
  uniform vec3 uColorFlat;

  varying vec3 vWorldPos;

  float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }

  void main() {
    vec3 dir = normalize(vWorldPos);
    float h = dir.y; // -1 (down) .. 1 (zenith)
    float horizonBand = smoothstep(-0.05, 0.35, h);

    vec3 col = uColorHorizon;
    col = mix(col, uColorMid, smoothstep(0.05, 0.4, h));
    col = mix(col, uColorZenith, smoothstep(0.3, 0.9, h));

    // Sun: low on horizon, in +Z direction (dir.z > 0, dir.y near 0)
    vec3 sunDir = normalize(vec3(0.0, 0.06, 1.0));
    float sunDot = max(dot(dir, sunDir), 0.0);
    float sun = pow(sunDot, 32.0);
    float sunHalo = pow(sunDot, 4.0);
    col += uColorSun * sun * 1.6;
    col += uColorSun * sunHalo * 0.35;

    // Cloud band — soft horizontal streaks near horizon
    if (h > -0.05 && h < 0.6) {
      float band = smoothstep(0.6, 0.0, h);
      vec2 cuv = vec2(atan(dir.z, dir.x), h);
      float cloud = sin(cuv.x * 6.0 + uTime * 0.02) * 0.5 + 0.5;
      cloud *= sin(cuv.x * 13.0 - uTime * 0.015) * 0.5 + 0.5;
      cloud = pow(cloud, 2.0);
      col = mix(col, vec3(0.06, 0.08, 0.12), cloud * band * 0.5);
    }

    // Stars (zenith only)
    if (h > 0.3) {
      vec2 grid = floor(dir.xy * 200.0);
      float s = hash(grid);
      if (s > 0.995) {
        float twinkle = 0.7 + 0.3 * sin(uTime * (2.0 + s * 10.0) + s * 30.0);
        col += vec3(0.8, 0.85, 1.0) * (s - 0.995) * 200.0 * twinkle * smoothstep(0.3, 0.7, h);
      }
    }

    // Fade to flat color when zoomed top-down
    col = mix(col, uColorFlat, smoothstep(0.7, 1.0, uZoomT));

    gl_FragColor = vec4(col, 1.0);
  }
`;