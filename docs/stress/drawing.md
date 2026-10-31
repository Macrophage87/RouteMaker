# How stress is drawn

[Index](README.md). All in `frontend/src/stressStyle.js` unless named. The map draws
the stress tiles (`GET /tiles/stress/{z}/{x}/{y}.pbf`, `src/core/stress_tiles.py`) with
a tile property `tier`. A road closed to cars at the ride time draws as tier 1 and a
path (`tierAt`, `facilityAt`, `:664-667`).

## Shapes: the same in every palette (`TIER_SHAPES`, `:52-63`)

Color is never the only cue: every tier differs in width and dash too.

| Tier | Legend label | Dash (in line widths) | Width (px) |
|---|---|---|---|
| 1 | Comfortable for most people | solid | 2.5 |
| 2 | Comfortable for most adults | [4, 1] | 3.25 |
| 3 | For confident riders | [2, 0.4] | 4.25 |
| 4 | Heavy or fast traffic | [8, 1] | 5 |
| 5 Avoid | Legal, but best avoided | [5, 1, 0.5, 1] (dash-dot, only Avoid) | 6.5 |

Each line has a casing 1 px wider on each side (`CASING_EXTRA_PX`, `:1159-1164`). The
accessibility switch (labeled High contrast) draws stronger: +0.5 px line, a casing 1.5 px a side, and the
calm tiers' casings pushed to black or white (`STRONG_*`, `:202-203`; `tiersFor`,
`:269-294`). The legend labels above are the legend's. The road panel's words are
441l's ([classification.md](classification.md)).

## Palettes (`PALETTES`, `:120-151`)

| Tier | Two-tone (default since 351; link `twotone`) | Warm (`blended`; link `warm`) | Color-blind-friendly (`cvd`; link `cool`; the accessibility switch, labeled High contrast) |
|---|---|---|---|
| 1 | `#9ed3ac` on `#2f5d47` | `#9ed3ac` on `#2f5d47` | `#d2eafc` on `#0a1a2f` |
| 2 | `#57a06c` on `#1a2638`, gaps `#7a8fa3` | the same | `#5d99d2` on `#0a1a2f`, gaps `#a7b4c1` |
| 3 | yellow `#f3c81a` on orange `#f28c28`, ringed `#1c1917` | amber `#bf730b` on `#45290a` | burnt orange `#cd4b0a` on `#0a1a2f` |
| 4 | orange `#f28c28` on red `#c81e1e`, ringed `#1c1917` | red `#c80018` on white | dark red `#6a0a06` on white |
| 5 Avoid | red `#d42020` on `#111111` (legend ring `#9aa0a6`) | near-black `#14040a` on coral `#ee3b2c` | blue-black `#08081e` on yellow `#f0e442` |

`DEFAULT_PALETTE = "twotone"` (`:153`). The link names (`?palette=`) say nothing about
who uses them (`:155-162`; OWNER-DECISIONS 321). The CVD palette keeps every adjacent
pair CIEDE2000 20 or more apart under protanopia, deuteranopia and tritanopia (Machado
2009), and its lightness falls tier by tier (`:105-118`; `stressContrast.test.ts`).
Unpaved ways use a brown ramp per palette, darker for busier
(`UNPAVED_PALETTES`, `:377-400`), on a natural or rough surface, and one grey ramp on
any other, gravel (`GRAVEL_PALETTES`; the owner, 2026-10-21), each with a dotted center mark (`UNPAVED_DASH`, `:1040`).
A trail with no surface mapped is dashed [2, 1.5] (`UNKNOWN_SURFACE_DASH`, `:425`).

**There is no dark-mode map palette.** `prefers-color-scheme: dark` restyles the panels
(`frontend/src/styles.css:47`, `:77`, `:2291`), and the map keeps the palette chosen
above.

## Zoom rules

| Zoom | What the tiles carry (`stress_tiles.py:20-50`, `:128-146`, `level_for` `:248-255`) | How it is drawn |
|---|---|---|
| 10-11 | Long traffic-free paths and trails only, and roads closed to cars at set times. z10 has a higher bar than z11 | Thinner: line x0.55 at z10, x0.75 at z11, rails x0.4 / x0.6, never under 1 px (`ZOOMED_OUT_*`, `:720-746`) |
| 12-13 | The **ride layer**: long connected paths, calm roads in runs of 2 mi [3.2 km] or more, timed car-free roads. **No road at LTS 3 or above** ([layers.md](layers.md)) | Full width. On a table without `calm_run_m` (built before 391), the old busy level instead: paths plus LTS 3+ roads, drawn faint (40% opacity, 0.6 width, a dark edge; `FAINT`, `:748`) |
| 14+ | Every segment | Busy roads solid from 14 (`SOLID_MIN_ZOOM`, `:696`). A busy road beside a separately mapped bikeway is hidden until 15 and faint after (`BESIDE_ROAD_MIN_ZOOM`, `:697`). Alleys from 16, faint (`ALLEY_MIN_ZOOM`, `:766`) |

The map asks for nothing past z14, and z15-16 draw from the z14 tile.

Other rules:

- **Painted lanes on LTS 4 and Avoid** are not drawn unless the rider turns them on
  (`HIGH_STRESS_LANE_MIN_TIER = 4`, `:1214`; filter at `:962-966`; switch stored per
  device, `:1217-1256`).
- Facility rails: path (purple, solid), protected (magenta, dashed), painted lane (light
  purple, dotted) (`FACILITIES`, `:1192-1203`). An unpaved trail and a trail with no
  surface get no path rail.
- Mountain-bike trails draw in their own not-for-routes look from z14 (`MTB_TRAIL`,
  `:880-905`; OWNER-DECISIONS 452a, 454).

## Half steps (441r-441v, 458-458b, 460.1; own colours 2026-10-30/31) **built**

Tiles keep `tier` an integer, so a half step is the lower tier plus `half: true`
(`core/stress_tiles.py`, ETag letter `h`); the route's sections say `half: true` too
(`core.routing.stress_spans`, `StressSpanOut.half`). Drawn by `halfRingLayers` (with the rings,
under the facility rails) and `halfStepLayers` (an outline and a line per lower level, 1-4, over
every tier line) in `frontend/src/stressStyle.js`.

- **Below zoom 15**, a half step draws exactly as its lower level (460.1: "The level
  below makes more sense"). 1.5 looks like LTS 1.
- **From zoom 15, in the default and warm palettes**, a paved half step has colours of its own
  (`HALF_PALETTES`; the owner, 2026-10-30: "There's definitely room in the color spectrum where we
  are drawing routes to include half steps", and 2026-10-31: "today's orange should be 3.5 with 4 at
  some sort of red and 4.5 darkred"): its own line and edge over its lower level's width and
  pattern, and its own ring where it has one. Default: 1.5 `#6fc48a` on `#2f5d47`, 2.5 `#9fb83a`
  on `#1a2638`, 3.5 `#f28c28` on `#c81e1e` ringed (the old LTS 4 look), 4.5 `#560a0e` on
  `#e3261c` ringed (the reverse of LTS 4, `#e3261c` on `#560a0e`). An unpaved half step keeps
  its level's brown or grey, and a trail whose surface is not mapped keeps its dashes (376). The
  route draws its sections in the same colours (`routeColours.ts`, classes `1h`-`4h`), and both
  legends list each half step after its level.
- **In the colour-blind-friendly palette** (`HALF_DASHED`; the owner, 2026-10-31: "keep dashes
  with the same rules") no in-between colour is far enough from both neighbours for every colour
  vision, so a half step keeps the lower level's whole look - base color, casing, width and its own
  pattern (441v) - and over it goes a dash in the next level's **base color** (441u), using
  Option A, sparse blocks (458), on the map and on the route (`routeHalfLayers`):
  - 1.5, 2.5, 3.5: dash [1.5, 4.5] at full line width, in the base color of LTS 2, 3 or 4;
  - 4.5: Avoid's dash-dot [5, 1, 0.5, 1] at LTS 4's width, in Avoid's base color. It is never
    drawn as Avoid (441k).
- **A low-contrast dash gets a thin outline** on the dash only (458b): the colour-blind palette's
  4.5 (Avoid's blue-black on LTS 4's dark red, about 1.6:1), white, at least 3:1 against both the
  dash and the line (`HALF_OUTLINES`), checked in `frontend/src/halfSteps.test.ts` and in the
  browser a11y suite (section 22). The outline is a layer under the dash, a pixel wider each
  side, with the dash pattern scaled to its own width; the route has one too.
- Drawing rules use the lower level (461a), so painted-lane hiding follows the lower
  level: a 3.5 road shows its lane, and a 4.5 road hides it.
- The road panel always shows the exact step and its words (441k-441l).

## The Mass Ride map (`frontend/src/massStyle.js`; OWNER-DECISIONS 325-327, 387, 415-422)

In Mass Ride the stress layers are hidden at every zoom: the LTS colors, facility
rails, trails and the ride layer (`setMassRide`, `stressStyle.js:831-835`;
`lib/mapGlue.ts`). The map draws the Mass Ride tiles (`src/core/mass_tiles.py`),
colored by carrying capacity in riders a minute at 6-8 mph, inside the District
only:

| Band (riders a minute) | Color | Width | Dash | From zoom |
|---|---|---|---|---|
| Under 60, bottleneck | red `#d7191c` | 4 px | short | 14 |
| 60 to 120, tight | orange `#f28e2b` | 5.5 px | long | 14 |
| 120 to 200, good | green `#1a9850` | 7 px | solid | 12 |
| 200 and up, wide open | purple `#6a3d9a` | 8.5 px | solid | 10 (only runs of 0.5 mi [0.8 km] or more) |

`MASS_BANDS`, `massStyle.js:60-71`. Each band has a 3:1 halo. **Avoid** shows at every
zoom in its own style, with no capacity color and the label "AVOID" (`MASS_AVOID`,
`:102`). Its junction icons are orange at LTS 3 and red at LTS 4 or Avoid
([routing-costs.md](routing-costs.md), section 5).

## The route's own stress view

The route panel shows a stress breakdown bar of meters per tier, each segment labeled
with its percentage (`frontend/src/lib/stressBar.ts`). Avoid is the route's magenta
there (OWNER-DECISIONS 397). Where the route has stress sections (`stress_spans`), each half step
ridden is its own segment in its own color, its key and screen-reader text naming it ("LTS 3.5");
without sections the bar shows whole-level totals. Under the elevation in the route
chart, the rolling stress chart (460.12, built in PR #34) replaces the stress strip on
every ride type but Mass Ride. Its area takes the map's LTS 2, 3 and 4 colors and the
stress bar's patterns, Avoid stretches are the magenta blocks marked "AVOID" ("A"
where narrow), and flagged junctions are an orange triangle or a red diamond
(`frontend/src/ElevationChart.tsx:292-362`).
An answer with no score keeps the strip (`:364-370`). See
[stress-number.md](stress-number.md), section 4.
