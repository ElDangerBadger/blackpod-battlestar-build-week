import { Canvas, useThree } from "@react-three/fiber";
import {
  Bloom,
  DepthOfField,
  EffectComposer,
  GodRays,
  Noise,
  SMAA,
  Vignette,
} from "@react-three/postprocessing";
import { AdaptiveDpr, Environment, Lightformer, PerformanceMonitor } from "@react-three/drei";
import { BlendFunction } from "postprocessing";
import { Suspense, useEffect, useMemo, useState } from "react";
import * as THREE from "three";

import CameraRig from "./CameraRig";
import ChartView from "./ChartView";
import ColorGrade from "./ColorGrade";
import MaBearing from "./MaBearing";
import Ocean from "./Ocean";
import Ship from "./Ship";
import ShipCallout from "./ShipCallout";
import ShipMarker from "./ShipMarker";
import Sky from "./Sky";
import SunDisc from "./SunDisc";
import Wake from "./Wake";
import { projectNavigatorOcean } from "./projection";
import type { NavigatorOceanMarket, ProjectedNavigatorOcean } from "./types";

export type NavigatorOceanSceneProps = Readonly<{
  data: NavigatorOceanMarket;
  projection: ProjectedNavigatorOcean;
  oceanExaggeration?: number;
  zoomT: number;
  reducedMotion: boolean;
  onZoomChange: (value: number) => void;
  onRuntimeUnavailable: () => void;
}>;

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

/**
 * Prop-only Build Week host for Battlestar Navigator V3's active renderer graph.
 * Mission facts are already validated before reaching this scene; this component
 * owns visual camera/effect state only and has no fetch, route, store, or API seam.
 */
export function NavigatorOceanScene({
  data,
  projection,
  oceanExaggeration = 1,
  zoomT,
  reducedMotion,
  onZoomChange,
  onRuntimeUnavailable,
}: NavigatorOceanSceneProps) {
  const [viewT, setViewT] = useState(zoomT);
  const [lowFx, setLowFx] = useState(reducedMotion);
  const [sunMesh, setSunMesh] = useState<THREE.Mesh | null>(null);
  // Restore V3's visual amplitude control in ship view; ease to the normal
  // analytical scale so exaggerated geometry cannot crop the full chart.
  const chartProgress = Math.max(0, Math.min(1, (viewT - 0.55) / 0.45));
  const visualExaggeration = 1 + (oceanExaggeration - 1) * (1 - chartProgress);
  const visualProjection = useMemo(
    () => visualExaggeration === 1 ? projection
      : projectNavigatorOcean(data, { oceanExaggeration: visualExaggeration }) ?? projection,
    [data, projection, visualExaggeration],
  );
  const sunPosition = useMemo(
    () => new THREE.Vector3(0.14, 0.085, -1).normalize().multiplyScalar(2000),
    [],
  );

  useEffect(() => {
    if (reducedMotion) {
      setLowFx(true);
      setViewT(zoomT);
    }
  }, [reducedMotion, zoomT]);

  const shipScale = Math.max(0.65, 2 - viewT * 1.35);
  const fxAmount = 1 - Math.min(1, viewT / 0.85);
  const qualityReduced = lowFx || reducedMotion;

  return (
    <>
    <Canvas
      aria-hidden="true"
      shadows={false}
      dpr={reducedMotion ? 1 : [1, 1.5]}
      frameloop={reducedMotion ? "demand" : "always"}
      gl={{ antialias: true, powerPreference: "high-performance" }}
      camera={{ position: [0, 6, -10], fov: 62, near: 0.1, far: 5000 }}
      onCreated={({ gl, scene }) => {
        gl.toneMapping = THREE.ACESFilmicToneMapping;
        gl.toneMappingExposure = 1.05;
        scene.fog = new THREE.Fog("#0a1424", 240, 1700);
      }}
    >
      {!reducedMotion ? <PerformanceMonitor onDecline={() => setLowFx(true)} /> : null}
      {!reducedMotion ? <AdaptiveDpr pixelated={false} /> : null}
      <ContextLossMonitor onLost={onRuntimeUnavailable} />

      <Suspense fallback={null}>
        <Environment resolution={256} frames={1}>
          <Lightformer
            intensity={1.1}
            color="#4a5f82"
            form="rect"
            scale={[200, 120, 1]}
            position={[0, 40, -60]}
            target={[0, 0, 0]}
          />
          <Lightformer
            intensity={3}
            color="#ffb066"
            form="circle"
            scale={[36, 36, 1]}
            position={[24, 10, -160]}
            target={[0, 0, 0]}
          />
          <Lightformer
            intensity={0.4}
            color="#101827"
            form="rect"
            scale={[200, 200, 1]}
            rotation={[Math.PI / 2, 0, 0]}
            position={[0, -20, 0]}
          />
        </Environment>

        <ambientLight intensity={0.32} color="#7e93ad" />
        <directionalLight position={[30, 50, -200]} intensity={0.95} color="#ffb066" />
        <directionalLight position={[-8, 10, 60]} intensity={0.45} color="#5677a0" />
        <hemisphereLight args={["#2c4868", "#1a0d05", 0.3]} />

        <Sky zoomT={viewT} reducedMotion={reducedMotion} />
        <Ocean volatility={data.summary.volatility} zoomT={viewT} reducedMotion={reducedMotion} />
        <Wake projection={visualProjection} viewT={viewT} />
        <MaBearing
          projection={visualProjection}
          maPeriod={data.ma_period}
          zoomT={viewT}
          viewT={viewT}
        />
        <ChartView
          projection={visualProjection}
          zoomT={viewT}
          viewT={viewT}
          maPeriod={data.ma_period}
          timeframe={data.timeframe}
        />
        <ShipMarker zoomT={viewT} reducedMotion={reducedMotion} />
        <Ship
          scale={shipScale}
          volatility={data.summary.volatility}
          zoomT={viewT}
          reducedMotion={reducedMotion}
        />
        <SunDisc
          position={sunPosition}
          opacity={0.82 * fxAmount}
          size={300}
          onReady={setSunMesh}
          reducedMotion={reducedMotion}
        />
        <CameraRig
          zoomT={zoomT}
          reducedMotion={reducedMotion}
          onZoomChange={onZoomChange}
          onViewChange={setViewT}
        />

        <EffectComposer multisampling={qualityReduced ? 0 : 4}>
          {!qualityReduced ? (
            <DepthOfField
              target={[0, 1.4, 0]}
              focalLength={0.02}
              bokehScale={1.7 * fxAmount}
              height={480}
            />
          ) : <></>}
          {!qualityReduced && sunMesh ? (
            <GodRays
              sun={sunMesh}
              blendFunction={BlendFunction.SCREEN}
              samples={30}
              density={0.9}
              decay={0.9}
              weight={0.26 * fxAmount}
              exposure={0.24}
              clampMax={0.9}
              blur
            />
          ) : <></>}
          <Bloom
            intensity={0.34}
            luminanceThreshold={0.62}
            luminanceSmoothing={0.4}
            radius={0.8}
            mipmapBlur
          />
          <ColorGrade zoomT={viewT} amount={0.6} />
          {!qualityReduced ? (
            <Noise
              premultiply
              opacity={0.05 * fxAmount}
              blendFunction={BlendFunction.OVERLAY}
            />
          ) : <></>}
          <Vignette eskil={false} offset={0.22} darkness={0.62} />
          <SMAA />
        </EffectComposer>
      </Suspense>
    </Canvas>
    {/* Screen-space readout stays clear of the ship regardless of orbit/pan. */}
    <ShipCallout
      summary={data.summary}
      symbol={data.symbol}
      currency={data.currency}
      zoomT={viewT}
    />
    </>
  );
}
