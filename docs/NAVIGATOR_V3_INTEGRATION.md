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

## Snapshot drift checks

`ui/navigator-renderer-source.json` records the pinned canonical commit, both
file hashes for every source-to-destination pair, and the reason each adaptation
exists. Source hashes describe exact Battlestar bytes; destination hashes describe
the reviewed Build Week integration, so they are deliberately separate.

Run `make navigator-check` without a Battlestar checkout to verify all integrated
renderer files against their recorded hashes. This check also runs before
`make cabin-test` and every `make cabin-build` variant. Every other file in the
renderer directory must be explicitly classified as a consumer-owned adapter;
test files and Finder metadata are excluded. Missing files, changed renderer
bytes, unknown additions, and symbolic links fail the check. Consumer adapters
must exist, but their contents are governed by the normal Cabin tests.

Run the upstream check when starting a renderer update or reviewing readiness:

```sh
make navigator-check-upstream BATTLESTAR_PATH=/path/to/blackpod_battlestar
```

It checks both the source blobs at the pinned commit and the current mapped files
in the selected checkout. An unrelated Battlestar commit does not fail the check
when the mapped renderer files are unchanged. A local-only pass explicitly says
that upstream was not checked. The script can also use an existing environment
variable with `python scripts/check_navigator_renderer.py --upstream`.

These are read-only checks. There is no auto-copy or auto-approve mode. A hash
match verifies reviewed bytes; it does not establish that a changed visual design
or contract is correct. The guard covers this mapped snapshot, not every file in
the canonical standalone application. For example, upstream `styles/app.css` is
tracked as a whole file even though only its in-scene rules are consumed, so an
unrelated stylesheet edit still prompts a review.

## Reviewed update workflow

1. Run both checks and inspect any drift before changing the snapshot. Compare
   the previous pinned canonical source, the new canonical source, and the current
   Build Week adaptation for each affected mapping. Inspect new imports and add
   any required renderer sources to the mapping.
2. Port only the required renderer changes, preserving the prop boundary,
   deterministic sampling, reduced motion, missing-data behavior, and existing
   safety restrictions below. Changes confined to a Build Week adaptation should
   retain the canonical pin and source hash and explain the local correction.
3. Review the actual diff, update the adaptation notes and only the affected
   destination hashes. For a canonical upgrade, record the new full commit ID and
   the exact source hashes at that commit. The selected checkout's mapped files
   must also match those hashes. Use `shasum -a 256 path/to/reviewed/file` to inspect
   an individual digest; do not regenerate the manifest merely to silence drift.
4. Run `make navigator-check-upstream`, `make cabin-test`, `make cabin-build`,
   and the production browser checks. Review the SVG overview, expanded ocean,
   camera transitions, reduced motion, and fallback against the same mission
   artifact before committing the source changes and manifest together.

A shared renderer package remains the longer-term integration path once
Battlestar exposes an importable package. Until then, this snapshot and its
reviewed updates keep the canonical source explicit without changing Battlestar.

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
| `scene/ShipCallout.tsx` | `ui/src/components/navigator-ocean/ShipCallout.tsx` | Summary supplied through props; screen-sized label without perspective shrinkage |
| `scene/ShipMarker.tsx` | `ui/src/components/navigator-ocean/ShipMarker.tsx` | Reused marker; reduced-motion support |
| `scene/SunDisc.tsx` | `ui/src/components/navigator-ocean/SunDisc.tsx` | Reused billboard visual |
| `scene/projection.ts` | `ui/src/components/navigator-ocean/projection.ts` | V3 stretch plus Build Week's bounded deterministic sampling |
| `scene/oceanHeight.ts` | `ui/src/components/navigator-ocean/oceanHeight.ts` | CPU/GPU surface parity; exact chart flattening |
| `scene/renderOrder.ts` | `ui/src/components/navigator-ocean/renderOrder.ts` | Reused overlay order constants |
| Relevant V3 in-scene rules in `styles/app.css` | `ui/src/components/navigator-ocean/navigator-ocean.css` | Scoped under `.navigator-ocean`; no global reset/font import; readable Cabin ship-price typography |

The existing Build Week files `NavigatorOceanBoundary.tsx`,
`NavigatorOceanView.tsx`, `types.ts`, `useReducedMotion.ts`, and `HowToRead.tsx`
form the consumer adapter. The Captain's Cabin continues to own routing,
presentation mode, replay state, the expanded dialog, the SVG overview, and
all user-facing safety copy.

The user-requested ship-price legibility adjustment keeps the original world
anchor and chart-transition fade, but omits Drei's `distanceFactor` so camera
distance cannot shrink its text. The Cabin label is 224 CSS pixels wide with a
32-pixel price, 16-pixel percentage, and 14-pixel MA-position text. No price
formatting, observations, camera behavior, or canonical source files changed.

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
