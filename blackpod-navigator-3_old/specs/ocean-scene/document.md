# Feature: Ocean 3D Scene

## Overview
React Three Fiber scene rendering: ocean water plane with grid + waves, sky/horizon gradient, ship at origin, color-segmented wake trail behind the ship along negative Z, yellow dashed MA "bearing" line projected on the water with floating price labels.

## Coordinate System
- **+X**: not used (reserved for fleet ships)
- **+Z**: into the screen (toward horizon = past wake is in **+Z**)
- **+Y**: up
- Ship sits at world origin `(0, 0.1, 0)`. The world translates around it.

## Mapping Data → World
- Most recent bar = `z = 0` (under the ship).
- Each historical bar steps `+z` by `STEP_Z = 1.2` units. So 500 bars span ~600 units → fits the camera far plane (1000).
- Price `c` mapped to **lateral offset** on the X axis around the MA centerline:
  - `dx = (c - ma_at_t) * priceToWorldScale * oceanExaggeration`
  - `priceToWorldScale = visualWidth / atr_band`, where `atr_band = atr * 8` → keeps wake within ±~40 units visually.
- The MA line is rendered along `(0, 0, z)` — exactly down the ship's bearing. Therefore wake's lateral offset from the MA line directly = price minus MA (visually).
  - This is the key insight that matches the reference image: the **dashed yellow line is the MA bearing**; the **wake meanders left/right of it** based on whether price was above or below MA at that historical moment.

## Visual Components

### Water
- `<Plane args={[2000, 4000]}>` rotated `-π/2` on X, at `y=0`.
- Custom shader (or drei `MeshDistortMaterial` fallback) with two layers:
  - Deep base color `#06121f` (near) → `#0b2238` (far horizon) gradient.
  - Animated displacement noise driven by `volatilityIntensity` (from summary.volatility): glass=0.02, gentle=0.1, moderate=0.25, high=0.5, storm=0.9.
- Faint **dashed grid lines** in shader: every 50 world units on X and Z. Lines are subtle white at 4% alpha. Matches the "chart projected on ocean" look.

### Sky
- `<Sky>` from drei, sunset preset OR a custom gradient skybox: deep slate top `#0a0f1a` → warm horizon `#3a2a1f` near the sun → orange glow `#e88a3c` at horizon center.
- Subtle stars (`<Stars>`) at low density for atmosphere.

### Ship
- Procedural geometry (no external GLB needed for MVP):
  - Hull: a flattened, elongated `BoxGeometry` with bevel via `ExtrudeGeometry` from a hull profile shape, painted matte dark red `#7a1f1f`.
  - Deck: white `#e8e6e0` flat box on top.
  - Cabin: small dark glass box `#1a2230` on top of deck.
  - Antenna mast: thin cylinder.
- Ship is at origin, facing **+Z** (toward horizon/future). Wake trails behind toward viewer is wrong — actually wake trails **behind into +Z** (past). Camera sits at **-Z**, looking toward **+Z**. So past is in front of viewer's gaze, ship in foreground. This matches the reference.
- Subtle bob (sin wave Y offset) driven by volatilityIntensity.

### Foam under ship
- A small white `Sprite` or oriented plane with a soft radial gradient texture, slightly emissive, scaled with volatility.

### Wake (color-segmented price trail)
- Built as a single `Line2` (drei `<Line>` with `vertexColors`) from points: `points[i] = (dx_i, 0.05, z_i)`.
- Per-vertex color:
  - `c > ma + 0.25%`: `#22c55e` (green)
  - `c < ma - 0.25%`: `#ef4444` (red)
  - else: `#9ca3af` (gray)
- Line width 4 px (uses Line2 thick line).
- Underneath, a wider, lower-opacity additive "glow" Line2 of the same path for soft halo.

### MA Bearing Line (yellow dashed)
- A second `Line2` from `(0, 0.1, 0)` to `(0, 0.1, +zMax)` — straight down the center of the world (the ship's bearing).
- Color `#facc15`, dashed (Line2 supports `dashed`), thick.
- Floating **price labels** every N bars (e.g. every 30 bars on daily): drei `<Html>` or `<Text>` rendered above the line at `z = stepZ * i`, showing `ma_at_that_bar` formatted (e.g. `4,800`).

### Price callout on ship
- `<Html>` next to the ship: dark glass card with:
  ```
  PRICE (SHIP)
  4,752.18
  +2.35%
  Above MA
  ```
- Tail/connector: a thin yellow line from card to ship.

### Atmosphere / Lighting
- `<ambientLight intensity={0.3}>` cool blue.
- `<directionalLight position={[5, 8, -10]} intensity={1.4} color="#ffb066">` — sunset key light from horizon direction (front).
- `<fog attach="fog" args={['#0a1424', 80, 800]}>` for haze that grays the far wake (matches reference image's distant haze).

### Postprocessing
- `@react-three/postprocessing`: subtle bloom on ship lights/foam/yellow line; vignette; chromatic aberration extremely subtle.

## Performance
- Wake decimation: cap to 500 points; if data > 500, sample evenly.
- Use `Line2` once and update `geometry.setPositions(flatArray)` in `useEffect` on data change — no per-frame allocations.
- Ship bob uses `useFrame` setting `mesh.position.y`.

## Acceptance Criteria
- Ship visible front-and-center; wake clearly behind extending to horizon.
- Yellow dashed line clearly visible going to horizon vanishing point.
- Wake segments visibly switch green/red around MA crossings.
- Storm volatility produces visibly choppy water; glass calm.
- 60 fps on desktop with 500 wake points.

## Status
Done.