# What a tier costs a route today

[Index](README.md). Sources: [literature.md](literature.md). Junctions:
[intersections.md](intersections.md).

Stress reaches a route in three layers:

1. **The Valhalla graph** (Valhalla 3.6.3, MIT license). Tags are written per way at
   graph build, and a weight, `use_roads`, is sent per request.
2. **RouteMaker's own ranking** (`src/core/refine.py`, `src/core/routing.py`). It
   reads the live segment table at route time and runs the calm search, the guards,
   the LTS 4 hold, the strict order and the worth rule.
3. **The junction model** (`src/routemaker/intersections.py`). It gives each junction
   on a traced route a cost in feet of quiet riding, which the ranking adds in.

Turn, gate, surface and hill costs are sent at every slider position and do not
depend on the tier (`src/core/presets.py:439-475`).

## 1. Valhalla: graph tags (`lua/routemaker_remap.lua`)

The tier reaches the transform as `rm:stress_tier` (`src/pipeline/run.py:2402`, read at
`lua/graph.lua:67`). Valhalla's bicycle edge cost is `time x (1 + grade +
accommodation x roadway stress)` (sif/bicyclecost.cc). The three writes below change
the cost and never the reported time. Each is written only where the way is already
open to a bicycle (`may_penalise`, `:1179-1192`) and never on a trail-class way.

| Write | Tiers | Effect | Graphs | Lines |
|---|---|---|---|---|
| `bicycle=use_sidepath` | 3, 4, 5 (and OSM's own alleys, priced as LTS 3) | Adds `3 x (1 - use_roads)` to the accommodation factor | All | `:531-576`; `STRESS_PENALTY_TIER = 3` `:1196` |
| Graded: `maxspeed:practical=140`, `lanes:forward`/`backward=15` | 4, 5 | The graph's top speed and lane count, which raise roadway stress. LTS 4's added cost is at least 2x LTS 3's at old slider positions 5-100 (today's about 4 and up) on roads posted up to 50 mph (1.99x at 55, 1.75x at 65) | All but no-trail (`facility_neutral`, `src/pipeline/run.py:1449-1450`) | `:578-611`; `GRADED_*` `:1200-1202` |
| `service=alley` | 5 | Valhalla charges `alley_penalty` each time a route enters an alley from a way that is not one. RouteMaker sends 1,800 s on every preset (`AVOID_ENTRY_PENALTY_S`, `presets.py:166`, sent at `:461`). The edge stays routable | All | `:613-643`; `AVOID_TIER = 5` `:1205` |
| Facility class (not stress) | any | Path `0.1+0.9u`, protected `(0.15+0.6u) x stress`, painted `(0.9+0.05u) x stress`, none `1.0 x stress`; `highway=cycleway` `0.8u` | Not on no-trail | `:1214-1245`, `:1290-` |

Graph variants (`src/pipeline/variants.py`; chosen by `variant_for_ride`,
`presets.py:661-677`):

| Variant | Used by | Stress on it |
|---|---|---|
| standard | Default, Trailmaxxing, Group Ride, Fast, Cargo Bike (no assist) | All three writes |
| weekend (twin of standard) | The same rides at a weekend time | As standard. A road closed to cars all weekend is a path at tier 1 (`run.py:1451-1452`) |
| off-road | Gravel, Mountain Goat (`OFFROAD_PRESETS`, `presets.py:658`) | All three writes. The mountain-bike class is open |
| e-bike | E-bike, and Cargo Bike with assist | All three writes |
| no-trail | Mass Ride | `use_sidepath` (weighted at nothing, since `use_roads` is 1) and the alley charge. No grading, no facility classes |

There is no per-tier knob in a request: `use_roads` is the only stress weight.

### The graded cost, as modeled (docs/DEVELOPMENT.md, "Graded stress")

The added cost per meter, as a multiple of the edge's time, for LTS 3 / LTS 4.
**DEVELOPMENT.md labels its columns 0/25/50/75/90/100. These are positions on the
slider before the 2026-10-01 rescale**, so `use_roads` = 1 - old/100. They map to
today's positions like this:

| `use_roads` | 1.0 | 0.871 | 0.486 | 0.10 | 0.0 |
|---|---|---|---|---|---|
| Position today | 0 | 10 (Fast) | 40 (Group, Goat, Gravel) | 70 (Default, E-bike, Cargo) | 80 (Cargo with passengers) and above |
| Old position | 0 | 12.9 | 51.4 | 90 | 100 |
| LTS 3 added (5 road types) | 0 | 0.47-0.80 (interpolated) | 2.05-4.06 (interpolated) | 4.13-10.54 | 4.75-12.84 |
| LTS 4 added (standard graph) | 0.82-1.14 | 2.44-2.94 (interpolated) | 9.63-11.56 (interpolated) | 26.08-32.62 | 32.14-40.52 |

The five road types are a 30 mph secondary with 1 lane each way; 35 mph and 40 mph
(painted lane) primaries with 2 lanes; a 45 mph trunk with 3 lanes; and a 55 mph
primary with 2 lanes. Values marked interpolated are linear between the table's
columns.

## 2. The slider (`presets.py:174-263`; mirrored in `frontend/src/lib/dials.ts:76-87`)

| Position | `use_roads` (`use_roads_for`, `:246-254`) | Calm rate (`calm_rate_for`, `:257-263`) | Intersection weight (`refine.intersection_weight`, `refine.py:214-219`) | Ranking |
|---|---|---|---|---|
| 0 | 1.000 | 0 | 0.25 | Score |
| 10 | 0.871 | 0 | 0.357 | Score |
| 40 | 0.486 | 0 | 0.679 | Score |
| 70 | 0.100 | 0 | 1.0 | Score |
| 80 | 0.000 | 0 | 1.0 | Score |
| 85 | 0.000 | 0.585 | 1.0 | Score |
| 90 | 0.000 | 1.824 | 1.0 | Score |
| 95 | 0.000 | 4.447 | 1.0 | Score |
| 100 | 0.000 | 10.0 (`CALM_RATE_MAX`) | 1.0 | Strict order + worth rule (`maxcalm_for`, `:309-312`) |

0-70 is the old 0-90, 70-80 the old 90-100, and 80-100 is new. The calm rate is
`10 x (e^(3t) - 1) / (e^3 - 1)` with `t = (s - 80)/20`. A rider may move the slider on
every preset except Mass Ride, which is locked at 0 (`stress_max=0`, `presets.py:542`).

## 3. Each preset's values (`presets.py:478-635`)

| Preset | Graph | Slider start | `use_roads` | Calm rate | Junction weight | Exposure weights (LTS 3/4/Avoid) | LTS 4 hold | Bike type, planning speed | Calm search runs |
|---|---|---|---|---|---|---|---|---|---|
| Default | standard | 70 | 0.10 | 0 | 1.0 | 1 / 2 / 3 | no | Hybrid, 11.2 mph [18 km/h] | yes, one crossing round |
| Trailmaxxing | standard | 100 | 0.0 | 10 (strict order) | 1.0 | 1 / 8 / 16 | yes | Cross, 12.4 mph [20 km/h] | yes, leg by leg (`long_calm`) |
| Group Ride | standard | 40 | 0.486 | 0 | 0.679 | 1 / 2 / 3 | no | Cross, 12.4 mph [20 km/h] | yes, one crossing round |
| Mass Ride | no-trail | 0, locked | 1.0 | 0 | (0.25; not used) | 1 / 2 / 3 | no | Hybrid, 6 mph [9.7 km/h] | **no** (`routing._refine_limit`, `routing.py:1195-1196`) |
| Mountain Goat | off-road | 40 | 0.486 | 0 | 0.679 | 1 / 2 / 3 | no | Cross, 12.4 mph [20 km/h] | no while the climb seek runs (hills start at 100), else one crossing round |
| Gravel | off-road | 40 | 0.486 | 0 | 0.679 | 1 / 2 / 3 | no | Cross, 12.4 mph [20 km/h] | yes, one crossing round |
| Fast | standard | 10 | 0.871 | 0 | 0.357 | 1 / 2 / 3 | no | Hybrid, 11.2 mph [18 km/h] | yes, one crossing round |
| Cargo Bike, carrying cargo | standard (e-bike with assist) | 70 | 0.10 | 0 | 1.0 | 1 / 2 / 3 | no | Hybrid, 8.7 mph [14 km/h] (11.2 mph [18 km/h] with assist) | yes, one crossing round |
| Cargo Bike, with passengers | standard (e-bike with assist) | 80 | 0.0 | 0 | 1.0 | 1 / 8 / 16 | yes | Hybrid, 8.7 mph [14 km/h] (11.2 mph [18 km/h] with assist) | yes, one crossing round |
| E-bike | e-bike | 70 | 0.10 | 0 | 1.0 | 1 / 2 / 3 | no | Hybrid, 14.9 mph [24 km/h] | yes, one crossing round |

Every preset sends `alley_penalty` 1,800 s (`presets.py:461`). "Calm search runs" means
`refine.refine` is called: at a calm rate of 0 it makes one crossing-only round
(`CROSSING_ONLY_ROUNDS`, `refine.py:89`, `:1523`), and above 0 up to 5 exclusion
rounds (`REFINE_MAX_ROUNDS`, `:88`). The search does not run for Mass Ride, fewer than
2 points, a long ride, a climb seek, a span over 18.6 mi [30 km] (except
Trailmaxxing), or too little time (`routing.py:1180-1207`). The exposure weights
come from `Exposure` (`presets.py:338-354`), chosen per carrying choice on Cargo Bike
(`:357-364`, `:606-607`).

## 4. RouteMaker's ranking

### The score (below the top of the slider)

`Analysis.score`, `refine.py:336-340`, in the router's cost seconds:

    score = router cost + quiet_cost x (rate x exposure_m + weight x junction_m + climb_weight x climb_m)

- `quiet_cost` = 2.2 x the time of a meter at the request's speed (`QUIET_COST_FACTOR`,
  `refine.py:141-144`, `quiet_cost_per_m` `:179-186`). That is 0.44 cost-seconds a meter
  at 11.2 mph [18 km/h].
- `exposure_m` = the meters of each tier times its exposure weight (`refine.py:654-658`).
  LTS 1-2 and unknown count 0.
- `junction_m` = the summed junction costs in meters (`intersections.penalty_m`).
- A candidate replaces the best only if it beats it by more than 10 cost-seconds
  (`IMPROVEMENT_EPS_S`, `refine.py:140`, `:567`). Where the calm search runs with a calm
  rate (above 80), a longer one must also be worth its extra miles, by the worth rule
  below at `worth_ratio` (`refine.py:519-525`, `:564-569`): 1 + 4 x the calm rate over
  its top, about 1.2 at 85, 1.7 at 90 and 2.8 at 95 (with a target, the target prices
  below apply instead: 10 up to it and 2.5 past it, `distance_charge_m`,
  `refine.py:511-516`) (the owner's "One rule", 2026-10-10,
  filed under OWNER-DECISIONS 435; not yet in the decisions file). Crossing avoidance
  alone (80 and below) has no such bar.

### The calm search (`refine.refine`, `refine.py:752-821`; `_search` `:1518-`)

It reads the router's route, then excludes (`exclude_locations`) the LTS 4 and Avoid
stretches first, and later every LTS 3 stretch of the newest candidate. Each sample
is one point per edge middle, 131 ft [40 m] apart, at most 60 a round and 150 in
all, and never within 0.31 mi [500 m] of an end or a via point (`refine.py:112-130`,
`calm_targets` `:709-734`, worst first `:1532-1533`, `:1554-1556`). In the
crossing-only round it excludes the approaches to junctions of 2,000 ft or more (red),
at most 3 (`crossing_targets`, `:737-749`). Mass Ride is skipped (`ctx.group`).

### The guards

- **Traffic wins**: a candidate whose exposure is more than 2% plus 164 ft [50 m] over
  the router's first route's is not taken (`EXPOSURE_TOLERANCE`, `EXPOSURE_SLACK_M`,
  `refine.py:131-138`, `_allowance` `:1443-1446`).
- **`calmer_or_own`**: an alternative the hills slider picked is kept only if its
  exposure is no worse than the router's own route (`routing.py:1002-1037`).
- **LTS 4 hold** (stress-averse rides only): refuse a candidate whose top figure (LTS 4
  and Avoid meters plus red junction cost) is more than 1 m over the router's first
  route, for the whole trip or for any leg (`more_lts4`, `refine.py:956-1009`;
  `routing._hold_refuses`, `routing.py:993-999`).

### The top of the slider (100): strict order and worth rule

- `Analysis.key` = (top, second, distance) (`refine.py:353-371`). Top = LTS 4 +
  Avoid meters + red junction cost in meters. Second = LTS 3 meters + orange junction
  cost. Distance = actual and effort-equivalent distance blended by the Hills slider
  (`level3` `:374-387`). Tie steps are 49 ft, 164 ft and 164 ft [15 m, 50 m and 50 m] (`MAXCALM_STEPS`, `:417`).
- **Worth rule** (OWNER-DECISIONS 268, 271): a longer candidate replaces a shorter one
  only when the stress it saves pays for the distance it adds (`worth_it`,
  `refine.py:528-543`). Stress saved is counted in LTS 3-equivalent meters with the
  *standard* weights on every ride (LTS 3 x1, LTS 4 x2, Avoid x3, red junction cost x2,
  orange x1; `WORTH_WEIGHTS`, `stress_weight_m`, `:442-464`). The price per meter saved:
  - no target distance: 5 m added (`WORTH_DEFAULT`), up to 1.6 x the router's route
    and at least 1 mi [1.6 km] more (`presets.py:286-287`);
  - up to a rider's target distance: 10 m added per meter saved (`WORTH_UP_TO_TARGET`,
    `refine.py:441`; the owner's "One rule", 2026-10-10, filed under 435), half the
    default's price;
  - past the target: 2.5 m added per meter saved (`WORTH_OVER_TARGET`), never past
    1.25 x the target (`presets.py:288`).
- If the top figure improves by more than its tie step, its saving counts on its own,
  so LTS 4 never loses to extra LTS 3 (`stress_saved_m`, `:478-497`).

## 5. The junction model (`src/routemaker/intersections.py`)

Costs are in feet of equivalent quiet-street riding (from the literature review: Broach,
Dill & Gliebe; Eugene; the Oregon and Mineta tables). Only a road at LTS 3 or above is
busy (`BUSY_TIER = 3`, `:46-49`, `:226-227`). Tier 5 reads as 4 (`_tier`, `:333-335`).
The crossed road's tier is the greater of its tier and its unsmoothed tier
(`src/core/junctions.py:765-773`).

| Situation | LTS 3 | LTS 4 / Avoid | Lines |
|---|---|---|---|
| Straight across, from the stopped side | 1,200 ft [366 m] | 3,000 ft [914 m] | `:56` |
| Straight across at a signal | 150 ft | 300 ft | `:60` |
| Left off a busy road, across oncoming traffic (none on a one-way; x0.4 at a signal) | 600 ft | 1,500 ft | `:142-143` |
| All-way stop | 75 ft | 75 ft | `:64` |
| Rider on the priority road | 25 ft | 25 ft | `:69` |
| Quiet street meets quiet street at a stop | 10 ft | - | `:75` |
| Right turn off a busy road | 15 ft | 15 ft | `:144` |

Factors applied to the stopped-side and left costs (`scale`, `:318-330`):

- speed: up to 25 mph x0.8, 30 x0.9, 35 x1.0, 40 x1.1, 45 x1.2, faster x1.3 (`:113-114`);
- lanes per direction: 1 x1.0, 2 x1.1, more x1.25 (`:117-118`);
- volume: up to 5,000 a day x0.85, 10,000 x0.95, 20,000 x1.05, more x1.2 (`:120-121`);
- rural, stopped side at 45 mph or more: x1.25 (`:124-125`).

The cost is capped at 4,500 ft (`:126`). Turning onto a busy road scales the
stopped-side cost by left x1.5, straight x1, right x0.1 (`:133`). Merging across
lanes to turn left costs 250 ft a lane, capped at 500 ft, the box turn; at a signal
the whole left is capped at 500 ft (`:153-157`, `merge_ft` `:358-362`, `left_from_ft`
`:365-377`). Crossing a slip lane costs 800 ft, half that at a signal (`:168-169`). A
trail crossing with no signal mapped costs x0.5 and is never red (`:88-94`,
`marked_unsignalised` `:445-451`). A divided road counts once, with the median refuge
at x0.75 (`:107`, `merge_nearby` `:660-`). Several events within 148 ft [45 m] add, each
after the costliest at half its cost (`:608-624`). The cost of each junction is the
worst of its movements (`cost_of`, `:384-442`).

**Severity** (`severity_of`, `:454-459`): orange (higher stress) from 600 ft, red (very
high stress) from 2,000 ft (`ORANGE_MIN_FT`, `RED_MIN_FT`, `:176-177`). **Mass Ride**
reads it differently (`assess(group=True)`, `:560-584`): orange for any flagged
crossing or left of an LTS 3 road, red for LTS 4 or Avoid, no marker for a left across
a one-way, and the cost unchanged.

How the cost is used: in the score at the intersection weight (section 4), as targets
for exclusion from 2,000 ft (`REFINE_MIN_EVENT_FT`, `refine.py:111`), and at the top of
the slider as part of the top (red) and second (orange) figures. Junctions under
600 ft count in the score and not at the top of the slider.

## 6. Avoid, in one place

| Where | What Avoid gets |
|---|---|
| Valhalla | LTS 4's per-meter price (graded, except on no-trail) plus 1,800 s on each entry, on every preset including Mass Ride |
| Exposure | 3 (standard) or 16 (stress-averse) |
| LTS 4 hold, strict order | Counted with LTS 4 in the top figure |
| Worth rule | 3 |
| Junctions | As LTS 4 |
| Mass Ride capacity | "Not used by a mass ride" where no width is known (`src/core/segment_info.py:679`). Drawn as "AVOID" in its own style ([drawing.md](drawing.md)) |
| Calm search | Excluded in the first round, with LTS 4 |

The 1,800 s entry charge is cost, not time. Since Valhalla's edge factor is never
below 1, it is worth at most 30 minutes of riding. Against a quiet street, which
costs about 2.2x its time (`QUIET_COST_FACTOR`), it is worth about 2.5 mi [4.1 km] of
quiet street at 11.2 mph [18 km/h]. At 12.4 mph [20 km/h] it is 2.8 mi [4.5 km], at
Mass Ride's 6 mph [9.7 km/h] 1.4 mi [2.2 km], at 8.7 mph [14 km/h] 2.0 mi [3.2 km], and
at 14.9 mph [24 km/h] 3.4 mi [5.5 km].
