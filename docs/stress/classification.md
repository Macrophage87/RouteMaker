# How a way gets its tier

[Index](README.md). Sources: [literature.md](literature.md). Junctions:
[intersections.md](intersections.md).

Paths are relative to the repository root and line numbers are
for `main` when this set was written. A tier is set once per data rebuild, in the
`CLASSIFY_STRESS` stage (`src/pipeline/run.py:1663-1864`), then changed by approved
override rows in `APPLY_OVERRIDES` (`run.py:1983-2091`). Stage order is at
`run.py:2723-2736`.

## The scale

| Tier | Name in the code | Road panel words (`src/core/segment_info.py:63-69`) | Legend words (`frontend/src/stressStyle.js:56-62`) |
|---|---|---|---|
| 1 | `Stress.LTS1` | Comfortable for everyone | Comfortable for most people |
| 2 | `Stress.LTS2` | Fine for adults | Comfortable for most adults |
| 3 | `Stress.LTS3` | For experienced cyclists | For confident riders |
| 4 | `Stress.LTS4` | High stress: busy, fast traffic | Heavy or fast traffic |
| 5 | `Stress.AVOID` | Avoid | Legal, but best avoided |

`src/routemaker/stress.py:117-128`. Tiers 1-4 are Furth's levels. Tier 5 is the owner's
"legal but to be avoided" (2026-09-27) and is never produced by the Furth tables. The
two sets of words differ today: the panel uses the owner's 441l words, and the legend
still has the earlier ones (460.10 says the legend switches to 441l's, with the
half-step editor). Half-step words (1.5 "Probably comfortable for older children",
2.5 "Fine for most confident adults", 3.5 "Stressful even for experienced cyclists",
4.5 "A very high-stress road") are **planned** (441l).

## Inputs

| Input | Where it comes from | How it is read |
|---|---|---|
| OSM tags | The region extract (Geofabrik, OSM contributors, ODbL) | `highway`, `maxspeed`, `lanes`/`lanes:forward`/`:backward`, `oneway`, `cycleway*` and width and buffer, `parking*`, `shoulder*`, `surface`, `tracktype`, `smoothness`, `motor_vehicle`/`motorcar`/`vehicle`/`access`, `bicycle`, `expressway`, `service`, `maxspeed:type`/`source:maxspeed` |
| Traffic counts (AADT) | DDOT 2024 Traffic Volume (DC Open Data), VDOT AADT, and the DC Roadway Block count where no count layer reached the way | Matched to ways by geometry (`src/pipeline/conflation.py`; `run.py:1635-1661`). A trail-class way never takes a motor count (`run.py:1637-1646`). |
| AADT smoothing | `src/pipeline/aadt_smoothing.py` | See below. |
| DC agency street record | DC Roadway Block (DDOT / DC GIS) | Posted speed, lanes, one-way, bike lane, parking and parking width override the way's own tags in the District (`run.py:1713-1749`; `conflation.overlay_road_facts`, `conflation.py:902-`; OWNER-DECISIONS 190). A bike facility OSM maps as a separate way stays there. The owner may withhold a block's speed (`agency_blocks` in an override file; see [overrides.md](overrides.md)). |
| Urban or rural | The coverage polygon's urban-area layer (U.S. Census Bureau) | Picks the default speed table (`stress.py:142-194`). |
| State | State polygons from the extract (`src/pipeline/states.py`; `run.py:1669-1675`) | DC's statutory 20 mph (15 mph in alleys) for an unposted way; MD and VA urban defaults (`stress.py:198-223`, `:788-806`). A missing state refuses the rebuild. |
| Divided roads | `src/routemaker/divided.py` | A one-way carriageway of a two-way road is scored as the two-way road (`stress.py:816`). |
| Separate bikeway beside a road | `routemaker.facility.separate_pairs` (`run.py:1702-1704`) | Counts as bike infrastructure for the arterial and collector floors. |
| Curated speed limits | `fixtures/speed/` (`src/routemaker/speed_corrections.py`; OWNER-DECISIONS 131) | Fill a missing `maxspeed` only. A posted speed wins (`run.py:1750-1752`). |
| Curated bike lanes | `fixtures/bike_lanes/` (`src/routemaker/bike_lanes.py`; OWNER-DECISIONS 433) | Add a painted lane OSM lacks (`run.py:1753-1755`). The owner's reading then holds the way at LTS 4 on 3 or more lanes a direction or at 45 mph or more (`bike_lanes.owner_tier`, `bike_lanes.py:86-102`; `run.py:1790-1795`). |
| Named corridors | `fixtures/corridors/` (`src/routemaker/corridors.py`; OWNER-DECISIONS 284-286, 294-296) | Set the tier on owner-judged stretches, matched by street name and an axis, not by way id (`run.py:1821-1830`). |
| Override rows | The `Override` table, approved rows only | Applied last. See [overrides.md](overrides.md). |

## Rule order in `classify` (`stress.py:704-746`, `_classify` `:749-1149`)

The order is speed, then facility, then volume, then surface (`stress.py:15-19`).
Each default that stands in for a missing tag errs toward higher stress and is
recorded in `assumed` (`stress.py:135-137`).

| Step | Rule | Lines |
|---|---|---|
| 1 | Trail-class way (`cycleway`, `footway`, `path`, `pedestrian`, `bridleway`, `steps`): LTS 1 | `:777-778`; `classes.py:19` |
| 2 | `motorway`, `motorway_link`: LTS 4 | `:780-781`; `classes.py:33` |
| 3 | Speed: posted `maxspeed`; else DC 20 (alley 15); else MD/VA urban defaults; else the urban or rural table by class (an unpaved rural lane is capped at 30 mph) | `:783-806`, tables `:142-223`, `:292` |
| 4 | Lanes per direction (default 1). An urban multi-lane street is read on the single-lane row. A one-way of up to 2 lanes gets relief. | `:808-822`, `:482-503` |
| 5 | Facility. A separated track: LTS 1. A painted lane: Furth's bike-lane table by speed, lanes and width (beside parking, the 15 ft [4.57 m] reach). A decent lane at 40 mph is LTS 3. With no lane, the mixed-traffic table, and the urban two-way floor (LTS 3, or LTS 4 at 30 mph or more over 8,000 vehicles a day) | `:859-895`; tables `:524-611`, `:506-521`, `:632-656` |
| 6 | Paved shoulder 4 ft [1.2 m] or wider: the bike-lane table, never worse than no provision | `:936-990`, `:250` |
| 7 | Volume, on single-lane roads with no provision. Up to 1,500 vehicles a day: one tier down (only to 35 mph, or when the speed was assumed). 8,000 or more: one tier up. Over 1,500 at 20 mph or less: LTS 1 becomes 2. An urban two-way floored road at LTS 4 drops to LTS 3 at 1,500 or less (same speed condition) | `:1023-1064`; thresholds `:298-301` |
| 8 | Floors without a facility: trunk, primary and secondary at least LTS 3 (OWNER-DECISIONS 141); tertiary at least LTS 2 (176). A rideable shoulder is read as a lane instead | `:1080-1098`, `:302-307` |
| 9 | Motor traffic restricted, with no count. `motor_vehicle=no`/`agricultural`/`forestry` (or `access=` the same with bicycles kept): at most LTS 1. `private`/`destination`/`permit`/`delivery`: at most LTS 2. One tier higher where posted over 30 mph | `:1105-1115`, `:1159-1220` |
| 10 | Rough surface (dirt, grass, `grade4`-`5`, very bad smoothness) floors LTS 1 to LTS 2. Gravel alone moves nothing | `:1130-1131`, `:1223-1237` |
| 11 | Avoid: `trunk`/`trunk_link`/`primary`/`primary_link` tagged `expressway=yes` and *posted* 50 mph or more becomes tier 5. The Furth rule is kept in the rule text | `:743-746`, `:670-681` |

## After `classify`, in `CLASSIFY_STRESS` and `APPLY_OVERRIDES`

1. **AADT smoothing** (`aadt_smoothing.py`; OWNER-DECISIONS 285, 296, 303) runs before
   `classify`. A way's count is replaced by the length-weighted median of the counts on
   the same street (name without quadrant, same state) within 1,312 ft [400 m], when the
   window holds at least 3 ways and 820 ft [250 m] of road (`aadt_smoothing.py:57-59`).
   It only ever lowers a count. The segment still publishes the agency's count. When the
   raw count gives a higher tier, that tier is kept as `stress_unsmoothed_tier`
   (`run.py:1775-1789`). The junction model and the calm-road breaks read the higher of
   the two, so the volume bunched at an intersection is charged there, not on the link
   (`src/core/junctions.py:765-773`; `src/pipeline/calm_roads.py:21-23`, `:98`). The
   rebuild can be told not to smooth (`RebuildContext.smooth_volume`, `run.py:621`).
2. **Curated bike lane, owner's tier** (`run.py:1790-1795`).
3. **Named corridors** (`run.py:1821-1830`): an entry sets the tier, up or down, for the
   ways of its role (through or side lanes) in its range along the axis. A way with a
   protected lane, a separate bikeway or a path facility is exempt, and so is any
   trail-class way (`corridors.py:27-33`). VALIDATE refuses a build whose sentinel
   stretches do not come out as the files say (`src/pipeline/lts_sentinels.py`).
4. **Stress override rows** (`run.py:2030`, `overrides.apply_stress`): they outrank
   everything above. See [overrides.md](overrides.md).
5. **Car-free for good** (`run.py:1386-`, called at `:2232`): a road closed to motor
   traffic outright, including by an approved `motor_vehicle=no` access row, becomes
   LTS 1 and a path, unless a curated stress row set its tier. A road closed to cars
   only at set times keeps its tier in the table. For a ride inside the closure it reads
   as tier 1 (`src/core/routing.py:377-382`; `stressStyle.js:664`) and is a path on the
   weekend graph (`run.py:1451-1452`).

## Closures are access, not stress

Whether a bicycle may use a way is decided by the access rules, never by the tier.

- OSM's `bicycle`/`access` tags, and the transform's own refusals (`lua/routemaker_remap.lua`).
- Military and secured areas (`src/pipeline/restricted_areas.py:1-40`): every road and
  path inside is closed (`rm:no_bicycle=military` / `secured`). The exceptions are an
  owner override, a numbered public route, a way signed `bicycle=designated` and, at the
  Pentagon, its listed ways (OWNER-DECISIONS 330, 437, 446-446c). Each closed way is
  listed in the rebuild's `military-closures.csv` / `secured-closures.csv`.
- Singletrack, natural-surface park trails and the other `rm:no_bicycle` reasons
  (`src/routemaker/trailaccess.py`, `singletrack.py`). Rated singletrack is closed on
  every graph. The mountain-bike class (`rm:no_bicycle=mtb`) is closed on every graph
  but the off-road one, which Gravel and Mountain Goat ride (`OFFROAD_PRESETS`,
  `src/core/presets.py:652-658`; `src/pipeline/variants.py:61-71`; OWNER-DECISIONS
  291(2)).
- The standing rule is to **err closed**: when it is unclear whether bikes are allowed,
  the way is closed, and the owner reopens it with evidence through an access override.

A closed way still has a tier in the segment table, but it is not routable. The stress
price is written only where the way is open to a bicycle: `use_sidepath` is never
written over a refusal (`may_penalise`, `routemaker_remap.lua:1179-1192`, `:551-562`).
The motor-restriction cap (step 9) is skipped on a way closed to bicycles
(`stress.py:1197-1210`; OWNER-DECISIONS 444).

## What the tier leaves the rebuild as

- `segment.stress_tier` (1-5), `stress_rule`, `stress_assumed`, the volume source, count
  and year, `stress_unsmoothed_tier`, and the adjustment columns (`schema.py:484`,
  `:571-579`; `src/pipeline/writers.py`).
- `rm:stress_tier` on each way of each graph variant (`run.py:2402`), read by
  `lua/graph.lua:67`, which drives the costs in [routing-costs.md](routing-costs.md).
- The stress tiles' `tier` property (`src/core/stress_tiles.py`), which [drawing.md](drawing.md) covers.
