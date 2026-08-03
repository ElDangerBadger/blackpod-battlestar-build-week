import { Canvas } from '@react-three/fiber';
import { EffectComposer, Bloom, Vignette } from '@react-three/postprocessing';
import { Suspense, useMemo } from 'react';
import * as THREE from 'three';
import { useMarket } from '../store';
import CameraRig from './CameraRig2';
import Ocean from './Ocean2';
import Sky from './Sky2';
import Ship from './Ship';
import Wake from './Wake2';
import MaBearing from './MaBearing2';
import ShipCallout from './ShipCallout';
import ChartAxis from './ChartAxis2';
import ShipMarker from './ShipMarker';
import { projectScene } from './projection';

export default function Scene2() {
  const data = useMarket((s) => s.data);
  const symbol = useMarket((s) => s.symbol);
  const oceanExag = useMarket((s) => s.oceanExag);
  const zoomT = useMarket((s) => s.zoomT);

  const projection = useMemo(() => {
    if (!data) return null;
    return projectScene({
      bars: data.points,
      oceanExag,
      visualHalfWidth: 38,
      visualDepth: 1600,
    });
  }, [data, oceanExag]);

  const volatility = data?.summary.volatility ?? 'gentle';

  // Ship scale fade for top-down — but minimum stays larger so the boat is always findable.
  const shipScale = Math.max(0.65, 2.0 - zoomT * 1.35);

  return (
    <Canvas
      shadows={false}
      gl={{ antialias: true, powerPreference: 'high-performance' }}
      camera={{ position: [0, 6, -10], fov: 62, near: 0.1, far: 5000 }}
      onCreated={({ gl, scene }) => {
        gl.toneMapping = THREE.ACESFilmicToneMapping;
        gl.toneMappingExposure = 0.95;
        scene.fog = new THREE.Fog('#0a1424', 240, 1700);
      }}
    >
      <Suspense fallback={null}>
        <ambientLight intensity={0.45} color="#7e93ad" />
        <directionalLight
          position={[3, 8, 200]}
          intensity={0.9}
          color="#ffb066"
        />
        <directionalLight position={[-6, 8, -8]} intensity={0.5} color="#5677a0" />
        <hemisphereLight args={['#2c4868', '#1a0d05', 0.35]} />

        <Sky zoomT={zoomT} />
        <Ocean volatility={volatility} zoomT={zoomT} />

        {projection && (
          <>
            <Wake projection={projection} />
            <MaBearing
              projection={projection}
              maPeriod={data!.ma_period}
              zoomT={zoomT}
            />
            <ChartAxis projection={projection} zoomT={zoomT} />
            {data && <ShipCallout summary={data.summary} symbol={symbol} zoomT={zoomT} />}
          </>
        )}

        <ShipMarker zoomT={zoomT} />
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