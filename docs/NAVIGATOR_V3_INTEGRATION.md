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
| `scene/Scene2.tsx` | `ui/src/components/navigator-ocean/NavigatorOceanScene.tsx` | Prop-only scene composition; no store; ship exaggeration eases to normal chart scale |
| `scene/CameraRig2.tsx` | `ui/src/components/navigator-ocean/CameraRig.tsx` | Host-owned zoom callbacks; canvas-scoped input |
| `scene/Ocean2.tsx` | `ui/src/components/navigator-ocean/Ocean.tsx` | Contract volatility prop; reduced-motion and chart flattening |
| `scene/Sky2.tsx` | `ui/src/components/navigator-ocean/Sky.tsx` | Contract-free visual component; reduced-motion support |
| `scene/skyGlsl.ts` | `ui/src/components/navigator-ocean/skyGlsl.ts` | Reused shader source |
| `scene/Ship.tsx` | `ui/src/components/navigator-ocean/Ship.tsx` | Reused model; visual props only |
| `scene/BowWake.tsx` | `ui/src/components/navigator-ocean/BowWake.tsx` | Reused effect; reduced-motion support |
| `scene/Spray.tsx` | `ui/src/components/navigator-ocean/Spray.tsx` | Fixed-seed particles replace `Math.random()` |
| `scene/Wake2.tsx` | `ui/src/components/navigator-ocean/Wake.tsx` | Consumes validated projection props |
| `scene/MaBearing2.tsx` | `ui/src/components/navigator-ocean/MaBearing.tsx` | Preserves missing-MA gaps |
| `scene/ChartView.tsx` | `ui/src/components/navigator-ocean/ChartView.tsx` | UTC labels; depth-safe full chart; gutter labels and bounded, series-aware hover |
| `scene/ColorGrade.tsx` | `ui/src/components/navigator-ocean/ColorGrade.tsx` | Reused post-processing effect |
| `scene/ShipCallout.tsx` | `ui/src/components/navigator-ocean/ShipCallout.tsx` | Supplied summary; transparent bottom-left screen-space label outside Canvas |
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

The user-requested ship-price placement now uses a transparent DOM overlay
outside Canvas, anchored 12 CSS pixels from the scene's left edge and 64 pixels
above its bottom. The ship stays unobscured; camera orbit/pan cannot move or
shrink the readout. Text shadow provides contrast without a panel background.
The original chart-transition fade is retained, as are the 224-pixel width,
32-pixel price, 16-pixel percentage, and 14-pixel MA-position text. No price
formatting, observations, camera behavior, or canonical source files changed.

The chart-readability adaptation offsets price and date labels 10 CSS pixels
outside their grid borders, without changing axis world coordinates or camera
scale. The highlighted latest-close badge sits just inside the right border so
it cannot overlap the price ticks in the outer gutter.
The existing hover plane selects the nearest rendered supplied observation and
highlights the closer price/MA series. The larger, viewport-bounded readout uses
two decimal places, preserves absent MA values, and clears during dragging or
pointer exit. Crosshair/markers render above the analytical lines. Hover does
not interpolate, fetch, mutate, or persist market data. Drawing remains a future
consumer presentation feature, not part of this adaptation.

### History and ship-scale controls

- Canonical `ui/Toolbar.tsx`'s Ocean Exag. range (0.2–2.5, step 0.05) maps to
  local state and controls in `NavigatorOceanView.tsx`, passed into the existing
  projection through `NavigatorOceanScene.tsx`. The original store is not
  imported. This scales wake/MA separation, not source prices, volatility, or
  the ship model. It eases back to 1× at full chart view to keep axes in frame.
- `historyWindow.ts` is a consumer-only view helper: 1M/3M/6M/1Y/All presets
  use UTC calendar lookbacks from the captured last bar, never the wall clock.
  A history-start slider selects a trailing suffix, keeps at least two supplied
  bars when possible, and always retains the latest close. No MA is recalculated
  after slicing. Hourly range labels preserve hours/minutes in UTC; daily and
  weekly labels remain date-only. SVG fallback MA labels use bars, not days.
  Source history, selected history, and rendered counts remain
  separate. Short windows use distinct time ticks rather than stacked labels.
- Canonical timeframe (`1h`, `1d`, `1wk`) and MA (`20`, `50`, `100`, `200`, `250`)
  setters call a standalone API through Zustand. That coupling remains excluded.
  The original context still has one captured pair. The user-approved optional
  `navigator_catalog` presentation supplement now supplies additional exact
  canonical captures. `NavigatorOceanBoundary.tsx` owns local interval/MA
  selection and forwards the selected dataset and timestamp to the existing
  renderer (or SVG fallback). No source computation or provider call is imported.
  See [captured dataset catalog](NAVIGATOR_CAPTURE_CATALOG.md).

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
