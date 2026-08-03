import { shaderMaterial } from '@react-three/drei';
import { extend, useFrame } from '@react-three/fiber';
import { useRef } from 'react';
import * as THREE from 'three';

const SkyMat = shaderMaterial(
  {
    uTime: 0,
    uZoomT: 0,
    uColorZenith: new THREE.Color('#040813'),
    uColorMid: new THREE.Color('#0c1830'),
    uColorHorizon: new THREE.Color('#3a2a1f'),
    uColorSun: new THREE.Color('#e88a3c'),
    uColorFlat: new THREE.Color('#070b14'),
  },
  /* glsl */ `
    varying vec3 vWorldPos;
    void main() {
      vWorldPos = position;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,
  /* glsl */ `
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
      float h = dir.y;
      vec3 col = uColorHorizon;
      col = mix(col, uColorMid, smoothstep(0.05, 0.4, h));
      col = mix(col, uColorZenith, smoothstep(0.3, 0.9, h));

      vec3 sunDir = normalize(vec3(0.0, 0.06, 1.0));
      float sunDot = max(dot(dir, sunDir), 0.0);
      float sun = pow(sunDot, 80.0);
      float sunHalo = pow(sunDot, 8.0);
      col += uColorSun * sun * 1.2;
      col += uColorSun * sunHalo * 0.18;

      if (h > -0.05 && h < 0.6) {
        float band = smoothstep(0.6, 0.0, h);
        float a = atan(dir.z, dir.x);
        float cloud = sin(a * 6.0 + uTime * 0.02) * 0.5 + 0.5;
        cloud *= sin(a * 13.0 - uTime * 0.015) * 0.5 + 0.5;
        cloud = pow(cloud, 2.0);
        col = mix(col, vec3(0.06, 0.08, 0.12), cloud * band * 0.5);
      }

      col = mix(col, uColorFlat, smoothstep(0.7, 1.0, uZoomT));
      gl_FragColor = vec4(col, 1.0);
    }
  `,
);
extend({ SkyMat });

interface SkyProps { zoomT: number; }

export default function Sky({ zoomT }: SkyProps) {
  const ref = useRef<THREE.ShaderMaterial & { uTime: number; uZoomT: number }>(null!);
  useFrame((_, delta) => {
    if (!ref.current) return;
    ref.current.uTime += delta;
    ref.current.uZoomT = zoomT;
  });
  return (
    <mesh>
      <sphereGeometry args={[2400, 32, 24]} />
      {/* @ts-expect-error custom drei shader material element */}
      <skyMat ref={ref} attach="material" side={THREE.BackSide} depthWrite={false} />
    </mesh>
  );
}