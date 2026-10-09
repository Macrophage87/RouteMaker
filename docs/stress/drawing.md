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

Each line has a casing 1 px wider on each side (`CASING_EXTRA_PX`, `:1153-1158`). The
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
(`UNPAVED_PALETTES`, `:377-400`), with a dotted center mark (`UNPAVED_DASH`, `:1034`).
A trail with no surface mapped is dashed [2, 1.5] (`UNKNOWN_SURFACE_DASH`, `:425`).

**There is no dark-mode map palette.** `prefers-color-scheme: dark` restyles the panels
(`frontend/src/styles.css:47`, `:77`, `:2291`), and the map keeps the palette chosen
above.

## Zoom rules

| Zoom | What the tiles carry (`stress_tiles.py:20-50`, `:128-146`, `level_for` `:247-254`) | How it is drawn |
|---|---|---|
| 10-11 | Long traffic-free paths and trails only, and roads closed to cars at set times. z10 has a higher bar than z11 | Thinner: line x0.55 at z10, x0.75 at z11, rails x0.4 / x0.6, never under 1 px (`ZOOMED_OUT_*`, `:720-746`) |
| 12-13 | The **ride layer**: long connected paths, calm roads in runs of 2 mi [3.2 km] or more, timed car-free roads. **No road at LTS 3 or above** ([layers.md](layers.md)) | Full width. On a table without `calm_run_m` (built before 391), the old busy level instead: paths plus LTS 3+ roads, drawn faint (40% opacity, 0.6 width, a dark edge; `FAINT`, `:748`) |
| 14+ | Every segment | Busy roads solid from 14 (`SOLID_MIN_ZOOM`, `:696`). A busy road beside a separately mapped bikeway is hidden until 15 and faint after (`BESIDE_ROAD_MIN_ZOOM`, `:697`). Alleys from 16, faint (`ALLEY_MIN_ZOOM`, `:766`) |

The map asks for nothing past z14, and z15-16 draw from the z14 tile.

Other rules:

- **Painted lanes on LTS 4 and Avoid** are not drawn unless the rider turns them on
  (`HIGH_STRESS_LANE_MIN_TIER = 4`, `:1208`; filter at `:956-960`; switch stored per
  device, `:1211-1250`).
- Facility rails: path (purple, solid), protected (magenta, dashed), painted lane (light
  purple, dotted) (`FACILITIES`, `:1186-1197`). An unpaved trail and a trail with no
  surface get no path rail.
- Mountain-bike trails draw in their own not-for-routes look from z14 (`MTB_TRAIL`,
  `:879-901`; OWNER-DECISIONS 452a, 454).

## Half steps (441r-441v, 458-458b, 460.1) **planned**

Built with the half-step editor. Tiles keep `tier` an integer, so a half step is the
lower tier plus a half flag (HALF-STEP-EDITOR-plan section 9).

- **Below zoom 15**, a half step draws exactly as its lower level (460.1: "The level
  below makes more sense"). 1.5 looks like LTS 1.
- **From zoom 15**, a half step keeps the lower level's whole look: base color, casing,
  width and its own pattern (441v). Over it goes a dash in the next level's **base
  color** (441u), using Option A, sparse blocks (458):
  - 1.5, 2.5, 3.5: dash [1.5, 4.5] at full line width, in the base color of LTS 2, 3 or
    4 (1.5's dash is LTS 2's `#57a06c` in the default palette and blue in CVD, 458a);
  - 4.5: Avoid's dash-dot [5, 1, 0.5, 1] at LTS 4's width, in Avoid's base color (the
    darker red, 441s-441t). It is never drawn as Avoid (441k).
- **Low-contrast dashes get a thin outline** on the dash only (458b): default palette
  3.5 (LTS 4's orange on LTS 3's yellow, about 1.5:1) and CVD 4.5 (Avoid's blue-black on
  LTS 4's dark red, about 1.6:1). The outline is at least 3:1 against both the dash and
  the line, checked in the browser a11y suite when built.
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
there (OWNER-DECISIONS 397). The rolling stress chart that replaces the strip (460.12)
is **planned** ([stress-number.md](stress-number.md), section 4).
