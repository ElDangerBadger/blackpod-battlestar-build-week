# Navigator V3 integration

## Authority

Battlestar is the canonical source for the Navigator renderer. This integration
was ported from Battlestar commit `78077983f7945528058102e466dd60a99d02622e`
(`blackpod-navigator-3/frontend/src`). Build Week owns only the Captain's Cabin
adapter and safety boundary around that renderer; it must not independently
evolve the renderer's visual design.

The canonical application is currently a private standalone Vite application,
not an exported library package. Build Week therefore carries the smallest
source-compatible renderer snapshot needed for a deployable Cabin. Future
renderer upgrades should be sourced from Battlestar, reconciled through the
mapping below, and kept behind the same prop-only boundary.

## Source to destination

| Battlestar Navigator V3 source | Build Week destination | Integration treatment |
| --- | --- | --- |
| `scene/Scene2.tsx` | `ui/src/components/navigator-ocean/NavigatorOceanScene.tsx` | Prop-only scene composition; no store |
| `scene/CameraRig2.tsx` | `ui/src/components/navigator-ocean/CameraRig.tsx` | Host-owned zoom callbacks; canvas-scoped input |
| `scene/Ocean2.tsx` | `ui/src/components/navigator-ocean/Ocean.tsx` | Contract volatility prop; reduced-motion and chart flattening |
| `scene/Sky2.tsx` | `ui/src/components/navigator-ocean/Sky.tsx` | Contract-free visual component; reduced-motion support |
| `scene/skyGlsl.ts` | `ui/src/components/navigator-ocean/skyGlsl.ts` | Reused shader source |
| `scene/Ship.tsx` | `ui/src/components/navigator-ocean/Ship.tsx` | Reused model; visual props only |
| `scene/BowWake.tsx` | `ui/src/components/navigator-ocean/BowWake.tsx` | Reused effect; reduced-motion support |
| `scene/Spray.tsx` | `ui/src/components/navigator-ocean/Spray.tsx` | Fixed-seed particles replace `Math.random()` |
| `scene/Wake2.tsx` | `ui/src/components/navigator-ocean/Wake.tsx` | Consumes validated projection props |
| `scene/MaBearing2.tsx` | `ui/src/components/navigator-ocean/MaBearing.tsx` | Preserves missing-MA gaps |
| `scene/ChartView.tsx` | `ui/src/components/navigator-ocean/ChartView.tsx` | UTC labels; depth-safe full chart |
| `scene/ColorGrade.tsx` | `ui/src/components/navigator-ocean/ColorGrade.tsx` | Reused post-processing effect |
| `scene/ShipCallout.tsx` | `ui/src/components/navigator-ocean/ShipCallout.tsx` | Summary supplied through props |
| `scene/ShipMarker.tsx` | `ui/src/components/navigator-ocean/ShipMarker.tsx` | Reused marker; reduced-motion support |
| `scene/SunDisc.tsx` | `ui/src/components/navigator-ocean/SunDisc.tsx` | Reused billboard visual |
| `scene/projection.ts` | `ui/src/components/navigator-ocean/projection.ts` | V3 stretch plus Build Week's bounded deterministic sampling |
| `scene/oceanHeight.ts` | `ui/src/components/navigator-ocean/oceanHeight.ts` | CPU/GPU surface parity; exact chart flattening |
| `scene/renderOrder.ts` | `ui/src/components/navigator-ocean/renderOrder.ts` | Reused overlay order constants |
| Relevant V3 in-scene rules in `styles/app.css` | `ui/src/components/navigator-ocean/navigator-ocean.css` | Scoped under `.navigator-ocean`; no global reset/font import |

The existing Build Week files `NavigatorOceanBoundary.tsx`,
`NavigatorOceanView.tsx`, `types.ts`, `useReducedMotion.ts`, and `HowToRead.tsx`
form the consumer adapter. The Captain's Cabin continues to own routing,
presentation mode, replay state, the expanded dialog, the SVG overview, and
all user-facing safety copy.

## Coupling removed at the boundary

- Canonical Zustand reads were replaced by read-only props derived from the
  validated `NavigatorMarket` mission contract.
- Canonical API calls, backend, provider configuration, and synthetic data
  paths were not ported.
- Harbor, toolbar, ticker/timeframe/MA selectors, zoom-strip application UI,
  standalone routing, and standalone layout were not ported.
- Particle randomness was replaced with fixed-seed generation so identical
  artifacts render identical geometry.
- Locale-sensitive chart dates were replaced with explicit UTC formatting.
- Global CSS, Google font imports, and root resets were replaced with scoped
  Cabin styles.
- WebGL capability, loading, context-loss, and render errors fall back to the
  existing read-only SVG renderer without changing mission facts.

## Preserved boundary

The renderer receives only validated mission observations and presentation
state. It cannot fetch, select another instrument, mutate a mission, approve a
handoff, submit an order, call a broker, or execute. Demo/Live selection and
deterministic replay remain Captain's Cabin concerns. The Mission Chart remains
the SVG overview; V3 loads lazily only when that overview is expanded.
