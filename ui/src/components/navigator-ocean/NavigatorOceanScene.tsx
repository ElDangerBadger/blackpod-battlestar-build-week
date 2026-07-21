import { Canvas, useThree } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import * as THREE from "three";

import { CameraRig } from "./CameraRig";
import { MaBearing } from "./MaBearing";
import { Ocean } from "./Ocean";
import { Ship } from "./Ship";
import { Wake } from "./Wake";
import type { NavigatorOceanMarket, ProjectedNavigatorOcean } from "./types";

type NavigatorOceanSceneProps = Readonly<{
  data: NavigatorOceanMarket;
  projection: ProjectedNavigatorOcean;
  zoomT: number;
  reducedMotion: boolean;
  onZoomChange: (value: number) => void;
  onRuntimeUnavailable: () => void;
}>;

const BOB_INTENSITY = {
  glass: 0.05,
  gentle: 0.18,
  moderate: 0.4,
  high: 0.7,
  storm: 1,
} as const;

function ContextLossMonitor({ onLost }: { onLost: () => void }) {
  const gl = useThree((state) => state.gl);
  useEffect(() => {
    const element = gl.domElement;
    const lost = (event: Event) => {
      event.preventDefault();
      onLost();
    };
    element.addEventListener("webglcontextlost", lost);
    return () => element.removeEventListener("webglcontextlost", lost);
  }, [gl, onLost]);
  return null;
}

export function NavigatorOceanScene(props: NavigatorOceanSceneProps) {
  const shipScale = Math.max(0.68, 2 - props.zoomT * 1.32);
  const bobIntensity = BOB_INTENSITY[props.data.summary.volatility];
  const fog = useMemo(() => new THREE.Fog("#07101d", 240, 1750), []);

  return (
    <Canvas
      aria-hidden="true"
      camera={{ position: [0, 6, 10], fov: 62, near: 0.1, far: 5000 }}
      dpr={[1, 1.5]}
      frameloop={props.reducedMotion ? "demand" : "always"}
      gl={{ antialias: true, powerPreference: "high-performance" }}
      onCreated={({ gl, scene }) => {
        gl.toneMapping = THREE.ACESFilmicToneMapping;
        gl.toneMappingExposure = 0.95;
        scene.fog = fog;
      }}
    >
      <color attach="background" args={["#07101d"]} />
      <ambientLight intensity={0.48} color="#8196ad" />
      <directionalLight position={[3, 8, 200]} intensity={0.9} color="#ffb066" />
      <directionalLight position={[-6, 8, -8]} intensity={0.5} color="#5677a0" />
      <hemisphereLight args={["#2c4868", "#1a0d05", 0.35]} />
      <Ocean volatility={props.data.summary.volatility} viewT={props.zoomT} reducedMotion={props.reducedMotion} />
      <Wake projection={props.projection} viewT={props.zoomT} />
      <MaBearing projection={props.projection} viewT={props.zoomT} />
      <mesh position={[0, 0.21, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[1.9, 2.2, 48]} />
        <meshBasicMaterial color="#f1cf69" transparent opacity={0.78} toneMapped={false} />
      </mesh>
      <Ship scale={shipScale} bobIntensity={bobIntensity} reducedMotion={props.reducedMotion} />
      <CameraRig zoomT={props.zoomT} reducedMotion={props.reducedMotion} onZoomChange={props.onZoomChange} />
      <ContextLossMonitor onLost={props.onRuntimeUnavailable} />
    </Canvas>
  );
}
