import { Canvas } from '@react-three/fiber';
import { EffectComposer, Bloom, Vignette } from '@react-three/postprocessing';
import { Suspense, useMemo } from 'react';
import * as THREE from 'three';
import { useMarket } from '../store';
import CameraRig from './CameraRig';
import Ocean from './Ocean2';
import Sky from './Sky2';
import Ship from './Ship';
import Wake from './Wake';
import MaBearing from './MaBearing';
import ShipCallout from './ShipCallout';
import ChartAxis from './ChartAxis';

export default function Scene() {
  const data = useMarket((s) => s.data);
  const symbol = useMarket((s) => s.symbol);
  const oceanExag = useMarket((s) => s.oceanExag);
  const zoomT = useMarket((s) => s.zoomT);

  // World scale: derive priceToWorld from the actual deviation range in the data
  // so the wake always reads as a snaking ribbon of consistent width.
  const { stepZ, priceToWorld, volatility } = useMemo(() => {
    if (!data) {
      return { stepZ: 3, priceToWorld: 0.5, volatility: 'gentle' as const };
    }
    let maxDev = 0;
    for (const b of data.points) {
      if (b.ma != null) {
        const d = Math.abs(b.c - b.ma);
        if (d > maxDev) maxDev = d;
      }
    }
    const priceToWorld = 22 / Math.max(maxDev, data.summary.last_price * 0.001);
    const totalBars = Math.min(data.points.length, 500);
    const targetZ = 1600;
    const stepZ = targetZ / Math.max(totalBars, 50);
    return {
      stepZ,
      priceToWorld,
      volatility: data.summary.volatility,
    };
  }, [data]);

  // Ship scale fade for top-down
  const shipScale = Math.max(0.3, 2.0 - zoomT * 1.7);

  return (
    <Canvas
      shadows
      gl={{ antialias: true, powerPreference: 'high-performance' }}
      camera={{ position: [0, 4, -10], fov: 55, near: 0.1, far: 5000 }}
      onCreated={({ gl, scene }) => {
        gl.toneMapping = THREE.ACESFilmicToneMapping;
        gl.toneMappingExposure = 0.95;
        scene.fog = new THREE.Fog('#0a1424', 220, 1700);
      }}
    >
      <Suspense fallback={null}>
        {/* Lighting */}
        <ambientLight intensity={0.45} color="#7e93ad" />
        <directionalLight
          position={[3, 8, 200]}
          intensity={0.9}
          color="#ffb066"
          castShadow={false}
        />
        <directionalLight position={[-6, 8, -8]} intensity={0.5} color="#5677a0" />
        <hemisphereLight args={['#2c4868', '#1a0d05', 0.35]} />

        <Sky zoomT={zoomT} />
        <Ocean volatility={volatility} zoomT={zoomT} />

        {data && (
          <>
            <Wake
              bars={data.points}
              oceanExag={oceanExag}
              stepZ={stepZ}
              priceToWorld={priceToWorld}
            />
            <MaBearing
              bars={data.points}
              stepZ={stepZ}
              maPeriod={data.ma_period}
              zoomT={zoomT}
            />
            <ChartAxis
              bars={data.points}
              stepZ={stepZ}
              priceToWorld={priceToWorld}
              zoomT={zoomT}
            />
            <ShipCallout summary={data.summary} symbol={symbol} zoomT={zoomT} />
          </>
        )}

        <Ship scale={shipScale} volatility={volatility} zoomT={zoomT} />

        <CameraRig />

        <EffectComposer>
          <Bloom intensity={0.28} luminanceThreshold={0.85} luminanceSmoothing={0.35} mipmapBlur />
          <Vignette eskil={false} offset={0.2} darkness={0.5} />
        </EffectComposer>
      </Suspense>
    </Canvas>
  );
}