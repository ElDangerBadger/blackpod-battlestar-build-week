# Feature: Camera Zoom Continuum (3D Ocean ↔ Top-down Chart)

## Overview
Mouse wheel and zoom slider continuously transition the camera from cinematic close-perspective (just behind the ship) → far perspective → high angle → top-down flat chart view. No mode switch. Matches the reference image's five thumbnails along the bottom.

## Goals
- Single continuous parameter `zoomT` in `[0, 1]` drives camera position, target, and FOV.
- At `zoomT = 1` the scene reads as a recognizable price chart (top-down, wake = price line, MA line straight along center, grid lines = chart gridlines).

## Camera Path
We interpolate camera position and target along `zoomT`:

| zoomT | name | cam position (x,y,z) | look-at (x,y,z) | FOV |
|-------|------|----------------------|------------------|-----|
| 0.00  | close perspective | (0, 4, -10) | (0, 1, 30)  | 55° |
| 0.30  | far perspective   | (0, 18, -40) | (0, 1, 80) | 50° |
| 0.65  | high angle        | (0, 90, -60) | (0, 0, 150) | 40° |
| 1.00  | top-down chart    | (0, 260, 0)  | (0, 0, 0)   | 25° |

We smoothly interpolate using catmull-rom or cubic-bezier easing on each axis. Easing: `easeInOutCubic` on the zoom parameter before lookup.

## Scene Adaptation as zoomT increases
- **Water displacement**: fade to 0 above `zoomT > 0.85` (top-down view should look like a flat chart, not waves).
- **Ship scale**: fade from 1.0 to 0.2 above `zoomT > 0.75` — at top-down, ship is just a marker dot at origin.
- **Price callout**: fade `<Html>` opacity to 0 above `zoomT > 0.6`.
- **Floating price labels along MA line**: scale up and become axis labels at right edge as we approach top-down. Use a separate set of right-edge price labels at `zoomT > 0.7` to mimic a chart's Y-axis.
- **Wake line width**: increases (more "chart-like") as `zoomT → 1`.
- **Fog**: opacity reduces to 0 at top-down (charts have no fog).
- **Sky / horizon**: fades to neutral dark background (`#0a0f1a`) at `zoomT > 0.8`.

## Controls
- **Mouse wheel**: `zoomT += deltaY * 0.0005`, clamped [0,1]. Smoothed with lerp toward target each frame (0.08 factor).
- **Top-right zoom slider**: range 0–1 with five tick marks labeled "Perspective / Far / High / Top-Down".
- **Right mouse drag**: rotate camera around its current path point — adds an azimuth offset (±45°). Disabled at zoomT > 0.9 (top-down has no rotation).
- **Left mouse drag**: pan in screen space — translates the look-at and camera together; clamped so user doesn't lose the ship.
- **Double-click**: reset to `zoomT = 0`, no pan, no rotation.

## Implementation
- A `<CameraRig>` component reads `zoomT` from store, computes target position/lookAt/FOV each frame in `useFrame`, then lerps the actual `state.camera`.
- Damping factor = 0.08 for buttery smoothness.
- Disable drei `OrbitControls` — we hand-roll input to avoid conflict with the zoom continuum.

## Acceptance Criteria
- Scrolling the wheel from min to max produces a fully continuous transition — no popping, no jumps.
- At `zoomT = 1`, the scene unmistakably reads as a price chart: top-down, wake = price line snaking around a straight horizontal MA line, with right-axis price ticks.
- At `zoomT = 0`, scene reads as cinematic over-the-shoulder ship view.

## Conventional chart orientation (Round 2 refinement)
The wake trails into **negative Z** (behind the ship); the camera sits at positive Z
and views the ship from behind, "following" it down its wake. At the top-down anchor
(`pos (0, 1340, -720)`, `look (0, 0, -720)`, `up = +X`) this makes the flattened chart
read **conventionally**: time on screen-X (oldest LEFT → ship/now RIGHT), price on
screen-Y (higher UP). The ship model is rotated 180° (bow toward -Z) to match.

### Chart-stretch (non-uniform price axis)
World geometry is true-scale (great for the 3D ocean) but at top-down the price axis
(±~38 world units) is dwarfed by the time axis (~1600 units), giving a near-flat line.
`chartStretchX(viewT)` smoothly inflates the price (X) coordinate of every wake/MA/axis
point from 1× → 14× as `viewT` moves 0.55 → 1.0. The underlying bar **values are
unchanged** — this is a pure visual remap, exactly like a chart library choosing
pixels-per-dollar. Implemented by multiplying point X in `Wake2`/`MaBearing2`/`ChartAxis2`
(quantized to limit Line2 geometry rebuilds), driven by a **smoothed, throttled** `viewT`
the `CameraRig` publishes so the stretch eases in lock-step with the camera.

### Ship findability
`ShipMarker` renders pulsing yellow rings + a solid center dot whose radius scales with
`zoomT` (baseR up to ~40, dotR up to ~13 world units at top-down) so the current-price
position is always locatable. The chart camera look-at is biased toward the ship so it
keeps right-edge margin. Left-drag pan lets the user reposition to find the boat.

## Status
Done. Verified across all four vantages (Close/Far/High/Chart) and multiple tickers
(SPY trending-up, TSLA volatile two-sided). Production build passes.