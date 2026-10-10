# The stress number

[Index](README.md). Sources: [literature.md](literature.md). Junctions:
[intersections.md](intersections.md).

Owner decisions 461 ("Just turn that into a number for stress"),
461a ("Then just have the half steps be midpoints"), 461b ("there should be a rolling
stress score that includes intersection stress"), 461c ("There's a cost to traveling
on a road and a cost to the intersection that's a sort of hidden number. Use that."),
461d (the metric is calm miles per actual mile, intersections included) and 461e (a
window of about a mile).

**No routing behavior changes.** Everything here is read from today's weights
([routing-costs.md](routing-costs.md)). What is not built yet is marked **planned**.

## 1. The value

    stress(segment) = its tier as a number

| Tier | 1 | 1.5 | 2 | 2.5 | 3 | 3.5 | 4 | 4.5 | 5 |
|---|---|---|---|---|---|---|---|---|---|
| Stress number | 1 | 1.5 | 2 | 2.5 | 3 | 3.5 | 4 | 4.5 | 5 (Avoid) |
| Status | built | planned | built | planned | built | planned | built | planned | built |

Today the value is `segment.stress_tier` (1-5). A road closed to cars at the time of the
ride counts as 1 (`src/core/routing.py:382`). A piece no segment rated is `unknown` and
has no number. Half steps arrive with the half-step editor (441i-441l; HALF-STEP-EDITOR-plan).
They are stored as the lower tier plus a half flag, so every integer reader keeps
working. The number is ordinal, as LTS is. Harvey, Fang & Rodriguez (MTI 19-20) warn
that averaging LTS levels assumes a spacing the scale was not designed with. That is
why the per-preset **cost multiplier** below, and not the level itself, is what gets
summed or averaged.

## 2. The cost multiplier per preset

For a preset P and a level L:

    M_P(L) = (a quiet meter's cost + the cost level L adds to a meter) / a quiet meter's cost

A quiet meter is a meter of quiet street (`QUIET_COST_FACTOR`, below). M is the tier's
increment only: the road's own roadway stress and its facility class are left out,
because they apply at any tier. The rolling score (section 4) prices each road by its own
whole routing cost instead, and falls back to this table's middles only where a trace gives
no road details. It is computed from today's code, in three parts.

- **Router.** `M = 1 + added(L) / 2.2`. `added(L)` is the graded cost per meter as a
  multiple of time ([routing-costs.md](routing-costs.md), section 1). 2.2 is
  `QUIET_COST_FACTOR`, the measured cost of a meter of quiet street as a multiple of its
  time (`src/core/refine.py:141-144`), the same exchange rate RouteMaker's own score uses.
  Valhalla's factor depends on the road's speed and lanes, so a range is given over the
  five modeled road types.
- **Calm rate above 80.** Plus `rate x w(L)`, the exposure weight `w` at that position's
  calm rate (`Analysis.score`, `refine.py:339-343`).
- **Top of the slider (100).** There is no per-meter price. Ranking is in the strict
  order, and the worth rule sets the exchange: a meter of LTS 3-equivalent stress saved
  is worth 5 m of extra distance with no target, and 2.5 m past a target
  (`refine.py:423-546`). The multiplier is then `1 + 5 x w_std(L)`, or `1 + 2.5 x w_std(L)`
  past a target. Up to a rider's target distance a meter of stress saved is worth 10 m
  of extra distance (`WORTH_UP_TO_TARGET`, `src/core/refine.py:444`; the owner's "One rule",
  2026-10-10, filed under 435; not yet in OWNER-DECISIONS), so the multiplier there is `1 + 10 x w_std(L)`. The rolling chart uses that
  price wherever a target is set (section 4).

Avoid also pays an **entry charge** of 1,800 s on each entry (`presets.py:167`). It is
shown as quiet-street distance at the preset's planning speed
(`1800 / (2.2 x 3.6 / km/h)` meters).

### Today, whole levels, at each preset's starting position

| Preset (position) | LTS 1-2 | LTS 3 | LTS 4 | Avoid per meter | Avoid entry |
|---|---|---|---|---|---|
| Mass Ride (0, locked, no-trail graph) | 1 | 1 | 1 (not graded) | 1 | 1.4 mi [2.2 km] |
| Any ride at 0 on the standard graph | 1 | 1 | 1.37-1.52 | as LTS 4 | as the preset |
| Fast (10) | 1 | 1.22-1.36 | 2.11-2.34 | as LTS 4 | 2.5 mi [4.1 km] |
| Group Ride, Mountain Goat, Gravel (40) | 1 | 1.93-2.85 | 5.38-6.25 | as LTS 4 | 2.8 mi [4.5 km] |
| Default (70) | 1 | 2.88-5.79 | 12.85-15.83 | as LTS 4 | 2.5 mi [4.1 km] |
| E-bike (70) | 1 | 2.88-5.79 | 12.85-15.83 | as LTS 4 | 3.4 mi [5.5 km] |
| Cargo Bike, carrying cargo (70) | 1 | 2.88-5.79 | 12.85-15.83 | as LTS 4 | 2.0 mi [3.2 km] (2.5 mi with assist) |
| Cargo Bike, with passengers (80) | 1 | 3.16-6.84 | 15.61-19.42 | as LTS 4 | 2.0 mi [3.2 km] (2.5 mi with assist) |
| Slider at 85, standard / stress-averse weights | 1 | 3.74-7.42 | 16.78-20.59 / 20.29-24.10 | 17.36-21.17 / 24.97-28.78 | as the preset |
| Slider at 90, standard / stress-averse | 1 | 4.98-8.66 | 19.26-23.07 / 30.20-34.01 | 21.08-24.89 / 44.79-48.60 | as the preset |
| Slider at 95, standard / stress-averse | 1 | 7.61-11.28 | 24.50-28.31 / 51.19-54.99 | 28.95-32.76 / 86.76-90.57 | as the preset |
| Trailmaxxing (100), no target | 1 | 6 | 11, and LTS 4 always ranks first | 16 | 2.8 mi [4.5 km] in Valhalla's candidates |
| Trailmaxxing (100), past a target | 1 | 3.5 | 6, and LTS 4 always ranks first | 8.5 | as above |

Notes:

- The stress-averse weights (1/8/16) count in the score only above 80. At 80 (Cargo with
  passengers) and at 100 (Trailmaxxing) they reach only the Traffic-wins guard,
  `calmer_or_own` and the LTS 4 hold. The worth rule always uses 1/2/3 (`refine.py:445-451`).
- The tier adds nothing at LTS 1 or LTS 2, in any layer: no rule separates them. The
  facility class still changes the cost. A traffic-free path costs `0.1 + 0.9u` of its
  time with no roadway term (`lua/routemaker_remap.lua:1240-1245`), a factor of about
  1.19 at Default, against about 2.2 for a quiet street (`QUIET_COST_FACTOR`). So a path
  meter counts about 0.55 quiet meters, on every graph except no-trail (Mass Ride), which
  has no facility classes. A street with a protected lane is priced `(0.15 + 0.6u)` times
  its stress, about 1.25 at Default, so it counts for about 0.57, the same as a path
  (`lua/routemaker_remap.lua:1237-1240`). The 1 in the table is a quiet street: a quiet
  street counts as 1, and paths and protected bike lanes count for less (except on Mass
  Ride). It is not every calm way.
- The Fast and Group columns are interpolated between the modeled positions
  ([routing-costs.md](routing-costs.md), section 1).
- Junction costs are separate. They are added at their point (section 4) and weighted by
  the intersection weight: 0.25 at 0, 0.357 at 10, 0.679 at 40, 1.0 from 70
  (`refine.py:214-219`). Mass Ride's routing charges none (the calm search does not run
  on it).

## 3. Half steps: midpoints (461a) **planned**

461a supersedes 460.2's geometric mean. A half step's cost multiplier and each of its
rule effects is the **arithmetic midpoint** of its two levels' values under today's
weights. On an on/off rule a tie goes to the **cautious** side, with two exceptions:
drawing uses the **lower** level (460.1), and **4.5 is never Avoid** (441k).

### Multipliers

| Preset (position) | 1.5 | 2.5 | 3.5 | 4.5 per meter |
|---|---|---|---|---|
| Mass Ride (0) | 1 | 1 | 1 | 1 |
| Fast (10) | 1 | 1.11-1.18 | 1.66-1.85 | 2.11-2.34 |
| Group, Goat, Gravel (40) | 1 | 1.47-1.92 | 3.66-4.55 | 5.38-6.25 |
| Default, E-bike, Cargo carrying cargo (70) | 1 | 1.94-3.40 | 7.87-10.81 | 12.85-15.83 |
| Cargo with passengers (80) | 1 | 2.08-3.92 | 9.38-13.13 | 15.61-19.42 |
| Trailmaxxing (100), no target / past target | 1 | 3.5 / 2.25 | 8.5 / 4.75 | 13.5 / 7.25 |

In the router, Avoid costs the same per meter as LTS 4, so 4.5 per meter is LTS 4's
there. Under the worth rule it is the midpoint of 11 and 16. 4.5 is never Avoid
(441k), so it does not get Avoid's Valhalla entry charge. A request carries one
`alley_penalty` value, charged each time a route enters a tier-5 way (only those carry
the alley mark), so a half-way price cannot be sent for 4.5 alone. The midpoint
rule would give RouteMaker's own ranking half the charge (900 s). **Owner to
confirm**; the default proposed here is none in Valhalla and 900 s in RouteMaker's
ranking.

What Valhalla can carry is decided at a rebuild, and only approximately:

- 2.5 needs a new graph tag that lifts the edge's cost to about the midpoint.
- 3.5 needs `use_sidepath` plus intermediate speed and lane tags.
- 4.5 is priced as LTS 4 until a costing fork.

All three are HALF-STEP-EDITOR-plan section 7.2, phase 3. RouteMaker's own ranking can
use the midpoints exactly (phase 2).

### Rule effects

| Rule (today) | 1.5 | 2.5 | 3.5 | 4.5 |
|---|---|---|---|---|
| Exposure weight, standard (0 / 1 / 2 / 3) | 0 | 0.5 | 1.5 | 2.5 |
| Exposure weight, stress-averse (0 / 1 / 8 / 16) | 0 | 0.5 | 4.5 | 12 |
| Worth rule weight (1 / 2 / 3) | 0 | 0.5 | 1.5 | 2.5 |
| LTS 4 hold, meters counted (`LTS4_TIERS`, `refine.py:960`) | 0 | 0 | 0.5 a meter | 1 (LTS 4 and Avoid both count 1) |
| Strict order: top / second figure | - | 0 / 0.5 | 0.5 / 0.5 | 1 / 0 |
| Junction, stopped side (0 / 1,200 / 3,000 ft, before factors) | 0 | 600 ft (orange) | 2,100 ft (red) | 3,000 ft |
| Junction at a signal (0 / 150 / 300 ft) | 0 | 75 ft | 225 ft | 300 ft |
| Left across oncoming (0 / 600 / 1,500 ft) | 0 | 300 ft | 1,050 ft (orange) | 1,500 ft |
| Busy-road gate, `BUSY_TIER` 3 (on/off) | no | yes (cautious) | yes | yes |
| Calm search target, tier 3+ / worst first 4+ (on/off) | no | yes (cautious) | yes / yes (cautious) | yes |
| Calm-road run membership, LTS 1-2 (on/off) | yes | no (cautious) | no | no |
| Calm-road run break, crossed road 3+ (on/off) | no | yes (cautious) | yes | yes |
| Mass Ride junction icon (orange 3, red 4+) | none | orange (cautious) | red (cautious) | red |
| "Not used by a mass ride", Avoid label | no | no | no | **no** (441k) |
| Map color and dash, painted-lane hiding (drawing) | lower level | lower level | lower level (lane drawn) | lower level (lane hidden, as LTS 4) |

The junction values are base costs. The speed, lane, volume and rural factors and the
cap apply afterwards, as for whole levels, and the orange and red thresholds (600 and
2,000 ft) are unchanged. Junctions read 4.5 like 4 (tier 5 is 4 there).

### Parked

GEOMETRIC-LTS-model.md proposed one geometric rule, `M = r^(L-2)` with `r` set by the
slider, and geometric means for half steps (460.2, 460.7). Owner decision 461 did not
adopt it ("keep what we have currently"), and 461a replaced the geometric mean with
midpoints. It is parked, with its owner questions.

## 4. The rolling stress chart (460.12, 461b-461e) **built**

The owner, 460.12: "A chart of rolling traffic stress makes more sense than a strip.
That way, spikes show up." 461c: build it from the costs the routing already charges.

It was built in PR #34 (merged to `main` as 3164c02), with each stretch priced by its
tier; each road's own routing cost followed on `claude/v0-4-0-stress-chart` (release
v0.4.0). The score is `src/routemaker/calm.py`, called from `route_profile`
(`src/core/routing.py`) with a `calm.Pricing` made in `plan` from the slider position and
the traced pieces with their edges' attributes (`_calm_pieces`). The answer carries it as
`profile.calm` (`ProfileCalmOut`, `src/core/api.py`).
The chart is drawn in `frontend/src/ElevationChart.tsx` from the rules in
`frontend/src/lib/profileChart.ts`, "The rolling stress chart" (`:1079-1345`).
docs/DEVELOPMENT.md, "The rolling stress chart", has the developer's account. Where the
built chart departs from the design that was here, the list at the end of this section
says so.

### Definition

The metric (461d) is **calm miles per actual mile, including intersections**. 1.0 is
all calm riding (all quiet streets); higher is more stress. Along a route of preset P, for a window of
length `w` centered on the point at distance `x`:

    R(x) = ( sum over rated stretches in the window of  length x M(stretch) )
         + ( sum over junctions in the window of  calm miles of the junction )
         + ( sum over Avoid entries in the window of  entry calm miles )
         ------------------------------------------------------------
                      rated length of the window

- The window (461e) is **1 mi [1.6 km]** (`WINDOW_M`), one setting, so it
  can be tuned. It is centered on each point and cut at the route's start and end, and
  the divisor is the rated length inside the cut window (`Rolling.at`). So a route
  shorter than the window uses its whole length. Each
  junction and each Avoid entry is counted once in every window that holds it. So a
  junction raises the line over the mile around it instead of spiking, and an LTS 2
  street that crosses many busy roads can read higher than a straight LTS 3 one.
- A stretch no segment rated counts in neither the calm miles nor the miles. A junction
  or Avoid entry on an unrated stretch is not counted. A
  window with nothing rated has no value, and the chart leaves a gap there.
- The **route total** is given in calm miles (and calm km): the sum of the numerator
  over the whole route (`total_calm_m`), over the rated length (`rated_m`).
- `M(stretch)` is **each road's own routing cost** (461c), over a quiet street's
  (`road_multiplier`, `edge_factor`, `piece_steps` in `calm.py`; `estimate: false`). This
  is the "computed in RouteMaker" route the design named, fed by the graph's own
  attributes rather than the segment table's:
  - The trace asks Valhalla for each edge's class, use, lane count, cycle lane, shoulder,
    truck route, bicycle network, tagged speed (`speed_limit`), density, roundabout flag
    and surface (`calm.TRACE_ATTRIBUTES`, added to `trace_leg`'s filter;
    `calm.road_of_edge` reads them onto each `Piece`). These are the edge as the router's
    graph holds it, after RouteMaker's transform: a graded LTS 4 or Avoid edge reports 15
    lanes, a painted lane the cycle-lane class the transform moved it to.
  - `edge_factor` restates Valhalla 3.9.1's bicycle edge cost (`sif/bicyclecost.cc`,
    `BicycleCost::EdgeCost`): `1 + accommodation x roadway stress`, the cycle-lane or path
    factor, the lane, truck-route and road-class terms, the speed penalty, the
    `use_sidepath` term from LTS 3 (never on a trail-class way; a graded edge carries it
    whatever the live tier says) and the bicycle-network factor. The edge's speed is the
    one the graph gave it: 140 km/h on a graded edge (a tagged speed to the builder, so
    130 on a rough surface and 175 on a turn channel), a tagged `maxspeed`, else the class
    default (`lua/vendor/graph_upstream.lua`) or, in a built-up area (density over 8),
    the graph builder's urban speed (`mjolnir/speed_assigner.h`), with its roundabout,
    link, driveway and rough-surface adjustments (`road_speed_kph`). It reproduces
    docs/DEVELOPMENT.md "Graded stress" table, all five roads at all six positions, to
    0.01, and hand-worked factors (`tests/test_calm.py`, `TestOwnCost`).
  - The **grade** and **surface** terms are left out (they are not traffic), and so are the
    turn, gate and alley charges (the junctions and Avoid entries are counted on their
    own, below). Stairs and ferries, whose router cost is time and not traffic, count at
    their tier's figure.
  - `M = factor / Q`, where `Q` is the same factor for a quiet street at the ride's
    `use_roads` (`quiet_factor`: a residential street with no lane at its default speed,
    urban, 20 mph [30 km/h], or rural, 22 mph [35 km/h], as the road is; 1.77 urban at
    Default). So **an all-quiet route reads exactly 1**, as 461d's "1.0 = all calm
    riding" says. (Dividing by `QUIET_COST_FACTOR`'s 2.2 would not: it was measured on
    the live router with the grade in, which each road's figure leaves out, and put a
    quiet street at 0.8 to 0.9.) At Default a traffic-free path reads about 0.67, a 25 mph
    [40 km/h] LTS 3 collector about 2.9, a 35 mph [56 km/h] two-lane-each-way LTS 3
    primary about 5.4, and a graded LTS 4 street from about 16 up. Above 80 the calm-rate
    term `rate x w(L)` is added, as before.
  - **Junctions and Avoid entries** are priced in quiet meters at 2.2 (the junction
    model's feet, Avoid's 1,800 s), so on this scale they are multiplied by 2.2 / `Q`
    (urban; `junction_scale`, 1.24 at Default) and cost the router what they did.
  - Each piece is **rated and graded as the stress section it lies in**
    (`with_section_tiers`), so a sliver folded into its neighbour (under 33 ft [10 m],
    `MIN_SPAN_M`) is neither a rated island inside an unrated section nor an Avoid entry
    the chart does not show. Junctions and Avoid entries are read against the sections.
  - **Stress edits.** The graph grades a road at a rebuild; a stress edit changes the live
    tier at once. Where the two disagree (a graded edge now rated under LTS 4, or an LTS 4
    or Avoid way the graph did not grade; `disagrees`), the road keeps the graph's cost and
    the answer says `estimate: true`.
  - At the top of the slider (Trailmaxxing), LTS 3 and up keep the worth rule's figure
    below, which is the ranking's own price there (it prices by level, not by road); LTS
    1-2 are priced by the road's own cost.
  - The figures are summed over every traced piece, and each section's step on the chart
    is the mean over the section (its calm meters over its rated meters), so a short busy
    piece folded into a quiet section still counts at its own road's cost (at the
    section's tier), and the answer keeps one step a section.
  - **The fallback.** Where a piece has no edge attributes (a router or test double not
    asked for them), it takes its tier's figure below, and the answer says `estimate:
    true`; the chart's key and source line then call it an estimate. This should not
    happen with the router in use.
- **The tier's figure** (`multiplier`), the fallback above:
  - LTS 1-2: the facility class. A traffic-free path counts `(1.1 + 0.9u) / 2.2`, a
    protected lane `(1 + (0.15 + 0.6u) x 1.2) / 2.2`, a painted lane
    `(1 + (0.9 + 0.05u) x 1.2) / 2.2`, and a quiet street 1, where `u` is the slider's
    `use_roads` (`facility_factor`). On the no-trail graph every
    LTS 1-2 stretch counts 1.
  - LTS 3 and up: `1 + added / 2.2 + rate x w(L)`. `added` is the **middle** of the five
    modeled road types' range behind section 2's table (`ADDED`),
    in a straight line between the modeled slider positions. So
    Default (70) counts LTS 3 as 4.33 and LTS 4 as 14.34, and Group Ride (40) 2.39 and
    5.82. The calm-rate term `rate x w(L)` counts only above 80. Avoid counts as LTS 4
    per meter, plus the calm-rate term at Avoid's own weight above 80. On the no-trail graph LTS 4 counts what LTS 3 does (no grading).
  - At the top of the slider (Trailmaxxing) the worth rule's exchange stands in:
    `1 + 5 x w_std(L)` with no target (LTS 3 6, LTS 4 11, Avoid 16), and
    `1 + 10 x w_std(L)` with a target set (11, 21 and 31), the price of the miles up to
    the target (section 2).
  - Half steps are not read: the score reads whole tiers. Half steps take the midpoint
    (461a) once they exist (**planned**, section 3).
- **Why not Valhalla's own per-node cost.** The trace's `node.elapsed_cost` gives the
  cost to each node, but in one figure with the grade term, the surface factor and the
  turn, gate and alley costs, which the trace does not give apart (it gives the turn's
  time, not its cost), so the traffic part cannot be taken out. Restating the formula
  from the edge's own attributes gives the traffic part alone. The cost is a restatement:
  a Valhalla upgrade that changes `bicyclecost.cc` must be checked against `edge_factor`
  (the Graded stress table test catches a change to the modeled roads).
- **Known gaps** (small): OSM's own alleys carry the `use_sidepath` mark at any tier
  (owner decisions 100, 110), and the transform makes them plain service roads, so the
  trace cannot tell them apart; they get their own cost without the sidepath term. A way
  the transform could not mark (a bicycle value other than "may ride") is still priced as
  marked from LTS 3. A direction-specific `maxspeed:forward`/`:backward` is read as the
  way's one speed. Valhalla also takes `maxspeed:advisory` and `maxspeed:practical` as the
  edge's speed, but the trace's `speed_limit` is only `maxspeed`, so a way tagged with
  either (other than the graded edges, read off their 15 lanes) is priced at its
  `maxspeed`.
- The owner's question of 2026-10-10, whether the per-tier estimate was acceptable, is
  **answered by building the exact cost, with the scale normalised so that a quiet street
  is exactly 1**. The scale the owner sees (1.0 = all calm riding) is unchanged; the
  estimate remains only as the fallback.
- A junction's calm miles are what the ranking charges for it. Every junction the model
  charges for counts, flagged or not: its cost (`cost_ft`, `intersections.cost_of`, see
  [intersections.md](intersections.md), after factors, merges and the cap) times the
  intersection weight at the ride's slider position (`junction_m`;
  `refine.intersection_weight`, passed by `plan`): 0.25 at 0, 0.679 at 40, 1.0
  from 70. 1,200 ft at weight 1.0 is about 0.23 calm mi [0.37 km]. At the top of the
  slider the worth rule's exchange applies instead: a red junction counts 5 x 2 x its
  cost, an orange one 5 x 1, and an unflagged one 0 (10 in place of 5 with a target).
  This is not the junction list's `calm_mi` (469b(5): the junction's own cost, without
  the weight, on `wip/isect-costs-c`). The two agree from 70 up. Where the route's
  junctions could not be read, none are counted, and the summary says so
  (`junctions_counted`).
- Avoid's **entry charge** (1,800 s) counts as quiet meters at the ride's speed
  (`avoid_entry_m`), at the point the route enters an Avoid stretch. With each road's own
  cost both are scaled by 2.2 / `Q`, above.
- The scale matches the multiplier. **1.0 is a quiet street**, and higher is more
  stress. Quiet meters per meter, or calm miles per mile.
- **Intersection costs are being revised (planned).** Decision 468 (option C) adds a
  severe tier for unsignalised LTS 4 and Avoid junctions, with a cap of about 2 mi
  [3.2 km], prices a merge for the lane changes before a left turn, and shows costs in
  calm miles; 468a adds a time-of-day factor (469c-e: x1.25 at the existing weekday rush
  windows, 7-10 AM and 4-7 PM; x1.0 at other weekday hours to about 9 PM; x0.85 weekend
  daytime; at night, about 9 PM to 7 AM, x0.5 in urban areas and x0.85 outside them;
  whether night applies every day of the week is still proposed). None of that is
  built. The chart reads the model's own `cost_ft`, so its junction figures follow when
  the revision merges.

### Words as a guide

The band edges are read from representative roads at their own cost at the ride's
slider position (`bands`, `BAND_*` in `calm.py`; sent as `profile.calm.bands`), so each
tier's typical road lands in its own band and the words match the map's colors (review
S3: a 25 mph LTS 3 street must not be said as "LTS 1 to 2 level"):

- the lower edge is halfway between a 25 mph [40 km/h] collector, one lane each way, no
  bike lane, at LTS 2 (the busiest typical calm road) and the same road at LTS 3 (the
  calmest typical LTS 3 road);
- the upper edge is halfway between a 40 mph [64 km/h] primary, two lanes each way, at
  LTS 3 (the busiest typical LTS 3 road) and a graded residential street at LTS 4 (the
  calmest LTS 4 road; on the no-trail graph, which grades nothing, a 45 mph [72 km/h]
  trunk, three lanes each way).

The words are the chart's own (`CALM_BANDS` and `calmBand`, `profileChart.ts`). For
Default (70):

| R | Words on the chart |
|---|---|
| up to 2.01 | LTS 1 to 2 level (the key: "Low stress (LTS 1 to 2 level)") |
| above 2.01, under 11.26 | LTS 3 level |
| 11.26 and up | LTS 4 level (the key: "LTS 4 level or higher") |

Each preset and slider position gives its own edges (at the top of the slider 3.6 and
8.5, where LTS 3 and LTS 4 are the worth rule's 6 and 11). At 0 on the slider, where LTS
3 costs no more than LTS 2, there is no LTS 3 band: both edges are the upper one, and only
the LTS 4 guide is drawn. The test (`test_each_tiers_typical_road_lands_in_its_own_band`)
checks the quiet streets, the collector and the arterial and two LTS 4 roads at six
slider positions. The edges stay a guide: an unusually fast LTS 2 road can read over the
lower edge. Avoid has no band of
its own. Where the mile around a point holds any Avoid, its words add ", Avoid nearby"
(`avoidNear`, `profileChart.ts:1222-1233`). Each flagged junction also keeps its own
marker, so averaging never hides a very high-stress crossing.

### What the rider sees

- **Where.** In the route chart, under the elevation, on every ride type but Mass Ride,
  in place of the stress strip (`ElevationChart.tsx:137-138`, `:292-362`). An answer with
  no score (an older one, or `calm: null` where the score failed) keeps the strip
  (`usableCalm`, `profileChart.ts:1108-1113`; `ElevationChart.tsx:156`, `:364-370`). A
  failure costs only the score (`route_profile`, `src/core/routing.py`). The route panel's
  stress bar is unchanged ([drawing.md](drawing.md)).
- **Scale.** A log scale from 0.5 to the next of 2, 5, 10, 20 ... above the highest
  value, the highest step and 1.15 times the upper guide, and at least 2 (`CALM_FLOOR`,
  `calmTop`, `calmScale`, `profileChart.ts:1089`, `:1128-1135`, `:1153-1157`), so a mile
  at 1.4 and a spike at 14 both read. The side is labeled "calm mi per mi"
  (`ElevationChart.tsx:295-300`), with figures from 0.5, 1, 2, 5, 10 ... to the top (any
  that would crowd are dropped, `calmTicks`, `profileChart.ts:1142-1150`), and a quiet
  line at 1. A value under 0.5 would be drawn at the floor, but none occurs: the lowest
  any road reads is about 0.53, a cycleway closed to walkers at the top of the slider in a
  rural area.
- **The picture.** The area under the line is filled in the map's LTS 2, 3 and 4 colors
  with the stress bar's patterns, cut where the line crosses a guide. Dotted guides at
  the band edges are labeled, for Default, "LTS 3 from 2.0" and "LTS 4 from 11.3" beside a
  swatch of the band (`ElevationChart.tsx:338-357`). A dashed step line shows each
  section's own figure, so a short busy stretch is still seen at its true level. Avoid
  stretches are the magenta blocks marked "AVOID" ("A" where narrow; `avoidLabel`,
  `profileChart.ts:137-139`). The flagged junctions are marked above the
  track: a triangle for higher stress (orange) and a diamond for very high stress (red)
  (`ElevationChart.tsx:358-360`). Unflagged junctions count in the line but have no
  marker.
- **The key** says the line is calm miles per mile (calm km per km) over the mile around
  each point, on a log scale, and that 1 is all quiet streets (`ElevationChart.tsx`).
  The source line under the chart says each road is priced by its own speed, lanes and
  bike lane (`calmSource`, `profileChart.ts`). Only where some stretch took its tier's
  figure (`estimate: true`) do the key and the source line call it an estimate.
- **Units.** Calm miles per mile, which is also calm km per km. The route total is
  given as calm miles with calm km after it, for example "7.4 calm mi (11.9 calm km)"
  (`calmDistance`, `profileChart.ts:1304-1308`); the app's text puts the metric in
  parentheses.
- **For a screen reader.** The chart is one slider named "Elevation and rolling stress
  along the route" (`ElevationChart.tsx:242`). At each point its spoken sentence adds,
  for example, "Mile around: 1.4 calm miles per mile, LTS 1 to 2 level" (", Avoid
  nearby" where it applies) and "Next junction to watch: very high stress, mile 1.4."
  (`profileChart.ts:687-689`, `:1228-1244`). The chart summary gives the route's total
  in calm miles over the rated distance, the average, the most stressful mile with the
  flagged junctions and Avoid in it, and, where they could not be read, that junctions
  are not counted (`calmSentences`, `profileChart.ts:1272-1294`). "Climbs and rolling
  stress as tables" adds a table with the value at the start, at a fixed interval set
  by the route's length (every half mile [0.8 km] on a route up to 10 mi [16 km], every
  mile up to 40 mi [64 km], every 2 mi [3.2 km] up to 80 mi [129 km], and every 5 mi
  [8 km] beyond), and at the end: what it reads as, and the flagged junctions since the row before
  (`calmRowStep`, `calmRows`, `profileChart.ts:1319-1345`; `ElevationChart.tsx:187`,
  `:731-755`).
- **Long routes.** Where a long route's profile is thinned, the sample at the highest
  window is kept, so the most stressful mile survives (`peak_index`; `route_profile`).

### Mass Ride

Mass Ride has no rolling score: `plan` passes no pricing for it, and its routing charges
no junction cost. The owner chose (2026-10-10) three Mass Ride charts instead: riders per
minute, corker load and elevation. They are built separately (docs/DEVELOPMENT.md, "The
rolling stress chart").

### Worked example (Default, made-up route, 2 mi [3.2 km])

An LTS 2 quiet street (M = 1) for the whole route, with one crossing at 1.0 mi:
straight across an LTS 4 road from a stop, 35 mph (x1.0), 2 lanes each way (x1.1), no
count, 3,000 x 1.1 = 3,300 ft, about 0.625 calm mi [1.0 calm km] at weight 1.0 (today's
figures). Window 1 mi [1.6 km]. The built score gives these figures, with the junction
in the tier's quiet meters (priced by each road's own cost it is scaled by 2.2 / 1.77,
about 0.78 calm mi, and the plateau reads about 1.78).

| Window centered at | Window | R |
|---|---|---|
| 0.0 mi (route start) | 0 to 0.5, cut at the start | 1.0 |
| 0.5 to 1.5 mi | holds the crossing | (1.0 + 0.625) / 1.0 = **1.625**, a plateau 1 mi wide |
| 2.0 mi (route end) | 1.5 to 2.0, cut at the end | 1.0 |

The route total is 2 + 0.625 = **2.625 calm mi** [4.2 calm km] over 2 mi. With the
junction counted once in every window around it, the crossing raises the line over the
whole mile rather than spiking. The step line stays at 1, and the crossing has its red
diamond at 1.0 mi (3,300 ft is over the 2,000 ft [610 m] red threshold).

### Where the built chart differs from the design

The design here recommended one 1 mi [1.6 km] window, each segment's own cost, the junction
markers and a faint step line. All four are built: each road's own cost followed the
first build (PR #34 priced each stretch by its tier, an estimate; the owner was asked on
2026-10-10 whether that was acceptable, and building the exact cost, normalised so a
quiet street is 1, answered it). The differences:

- **The step line shows each section's mean**, not every edge: the sums run over every
  traced piece at its own cost, but the answer keeps one step a stress section.
- **The band edges come from representative roads**, not the half-step midpoints of the
  tier figures (Words as a guide, above).
- **Only flagged junctions have a marker.** Every junction counts in the line and the
  total, but only the orange and red ones are marked and listed (461b asked for each
  junction to be "shown as a spike at its location"). This has not been put to the
  owner yet (an open point).
- **With a target at the top of the slider**, the worth rule's figure is 10, the price
  up to the target, not 2.5, the price past it. This has not been put to the owner yet
  (an open point).
- **The words** are "LTS 1 to 2 level", "LTS 3 level" and "LTS 4 level", not the road
  panel's words, and Avoid is ", Avoid nearby" rather than a band of its own. This has
  not been put to the owner yet (an open point).
- **Mass Ride** has its own three charts instead, and **half steps** are not read (both
  above).

Still **planned**: half steps (section 3),
the junction revision (467, 468, 468a with 469c-e's time bands; none of it is built), and
4.5's entry charge (section 3, an owner question).
