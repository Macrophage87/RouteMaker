# The stress number

[Index](README.md). Owner decisions 461 ("Just turn that into a number for stress"),
461a ("Then just have the half steps be midpoints"), 461b ("there should be a rolling
stress score that includes intersection stress") and 461c ("There's a cost to traveling
on a road and a cost to the intersection that's a sort of hidden number. Use that.").
**No routing behaviour changes.** Everything here is read from today's weights
([routing-costs.md](routing-costs.md)). What is not built yet is marked **planned**.

## 1. The value

    stress(segment) = its tier as a number

| Tier | 1 | 1.5 | 2 | 2.5 | 3 | 3.5 | 4 | 4.5 | 5 |
|---|---|---|---|---|---|---|---|---|---|
| Stress number | 1 | 1.5 | 2 | 2.5 | 3 | 3.5 | 4 | 4.5 | 5 (Avoid) |
| Status | built | planned | built | planned | built | planned | built | planned | built |

Today the value is `segment.stress_tier` (1-5). A road closed to cars at the time of the
ride counts as 1 (`src/core/routing.py:365`). A piece no segment rated is `unknown` and
has no number. Half steps arrive with the half-step editor (441i-441l; HALF-STEP-EDITOR-plan).
They are stored as the lower tier plus a half flag, so every integer reader keeps
working. The number is ordinal, as LTS is. Harvey, Fang & Rodriguez (MTI 19-20) warn
that averaging LTS levels assumes a spacing the scale was not designed with. That is
why the per-preset **cost multiplier** below, and not the level itself, is what gets
summed or averaged.

## 2. The cost multiplier per preset

For a preset P and a level L:

    M_P(L) = routing cost of 1 m at level L / routing cost of 1 m of calm (LTS 1-2) riding

It is computed from today's code, in three parts.

- **Router.** `M = 1 + added(L) / 2.2`. `added(L)` is the graded cost per metre as a
  multiple of time ([routing-costs.md](routing-costs.md), section 1). 2.2 is
  `QUIET_COST_FACTOR`, the measured cost of a metre of quiet street as a multiple of its
  time (`src/core/refine.py:136-139`), the same exchange rate RouteMaker's own score uses.
  Valhalla's factor depends on the road's speed and lanes, so a range is given over the
  five modelled road types. The unrated road's own roadway stress is left out, since it
  applies at any tier.
- **Calm rate above 80.** Plus `rate x w(L)`, the exposure weight `w` at that position's
  calm rate (`Analysis.score`, `refine.py:321-325`).
- **Top of the slider (100).** There is no per-metre price. Ranking is in the strict
  order, and the worth rule sets the exchange: a metre of LTS 3-equivalent stress saved
  is worth 5 m of extra distance with no target, and 2.5 m past a target
  (`refine.py:405-508`). The multiplier is then `1 + 5 x w_std(L)`, or `1 + 2.5 x w_std(L)`
  past a target. Up to a rider's target distance, distance is free and ranking is purely
  by the order.

Avoid also pays an **entry charge** of 1,800 s on each entry (`presets.py:161`). It is
shown as quiet-street distance at the preset's planning speed
(`1800 / (2.2 x 3.6 / km/h)` metres).

### Today, whole levels, at each preset's starting position

| Preset (position) | LTS 1-2 | LTS 3 | LTS 4 | Avoid per metre | Avoid entry |
|---|---|---|---|---|---|
| Mass Ride (0, locked, no-trail graph) | 1 | 1 | 1 (not graded) | 1 | 1.4 mi [2.2 km] |
| Any ride at 0 on the standard graph | 1 | 1 | 1.37-1.52 | as LTS 4 | as the preset |
| Fast (10) | 1 | 1.22-1.36 | 2.11-2.34 | as LTS 4 | 2.5 mi [4.1 km] |
| Group Ride, Mountain Goat, Gravel (40) | 1 | 1.93-2.85 | 5.38-6.25 | as LTS 4 | 2.8 mi [4.5 km] |
| Default (70) | 1 | 2.88-5.79 | 12.85-15.83 | as LTS 4 | 2.5 mi [4.1 km] |
| E-bike (70) | 1 | 2.88-5.79 | 12.85-15.83 | as LTS 4 | 3.4 mi [5.5 km] |
| Cargo Bike, carrying cargo (70) | 1 | 2.88-5.79 | 12.85-15.83 | as LTS 4 | 2.0 mi [3.2 km] (2.5 mi with assist) |
| Cargo Bike, with passengers (80) | 1 | 3.16-6.84 | 15.61-19.42 | as LTS 4 | 2.0 mi [3.2 km] |
| Slider at 85, standard / stress-averse weights | 1 | 3.74-7.42 | 16.78-20.59 / 20.29-24.10 | 17.36-21.17 / 24.97-28.78 | as the preset |
| Slider at 90, standard / stress-averse | 1 | 4.98-8.66 | 19.26-23.07 / 30.20-34.01 | 21.08-24.89 / 44.79-48.60 | as the preset |
| Slider at 95, standard / stress-averse | 1 | 7.61-11.28 | 24.50-28.31 / 51.19-54.99 | 28.95-32.76 / 86.76-90.57 | as the preset |
| Trailmaxxing (100), no target | 1 | 6 | 11, and LTS 4 always ranks first | 16 | 2.8 mi [4.5 km] in Valhalla's candidates |
| Trailmaxxing (100), past a target | 1 | 3.5 | 6, and LTS 4 always ranks first | 8.5 | as above |

Notes:

- The stress-averse weights (1/8/16) count in the score only above 80. At 80 (Cargo with
  passengers) and at 100 (Trailmaxxing) they reach only the Traffic-wins guard,
  `calmer_or_own` and the LTS 4 hold. The worth rule always uses 1/2/3 (`refine.py:419-425`).
- LTS 1 and LTS 2 cost the same in every layer today.
- The Fast and Group columns are interpolated between the modelled positions
  ([routing-costs.md](routing-costs.md), section 1).
- Junction costs are separate. They are added at their point (section 4) and weighted by
  the intersection weight: 0.25 at 0, 0.357 at 10, 0.679 at 40, 1.0 from 70
  (`refine.py:209-214`). Mass Ride's routing charges none (the calm search does not run
  on it).

## 3. Half steps: midpoints (461a) **planned**

461a supersedes 460.2's geometric mean. A half step's cost multiplier and each of its
rule effects is the **arithmetic midpoint** of its two levels' values under today's
weights. On an on/off rule a tie goes to the **cautious** side, with two exceptions:
drawing uses the **lower** level (460.1), and **4.5 is never Avoid** (441k).

### Multipliers

| Preset (position) | 1.5 | 2.5 | 3.5 | 4.5 per metre |
|---|---|---|---|---|
| Mass Ride (0) | 1 | 1 | 1 | 1 |
| Fast (10) | 1 | 1.11-1.18 | 1.66-1.85 | 2.11-2.34 |
| Group, Goat, Gravel (40) | 1 | 1.47-1.92 | 3.66-4.55 | 5.38-6.25 |
| Default, E-bike, Cargo carrying cargo (70) | 1 | 1.94-3.40 | 7.87-10.81 | 12.85-15.83 |
| Cargo with passengers (80) | 1 | 2.08-3.92 | 9.38-13.13 | 15.61-19.42 |
| Trailmaxxing (100), no target / past target | 1 | 3.5 / 2.25 | 8.5 / 4.75 | 13.5 / 7.25 |

In the router, Avoid costs the same per metre as LTS 4, so 4.5 per metre is LTS 4's
there. Under the worth rule it is the midpoint of 11 and 16. 4.5 is never Avoid
(441k), so it does not get Avoid's Valhalla entry charge. Valhalla charges
`alley_penalty` once per request, and only the tier-5 ways carry the alley mark. The
midpoint rule would give RouteMaker's own ranking half the charge (900 s). **Owner to
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
| LTS 4 hold, metres counted (`LTS4_TIERS`, `refine.py:818`) | 0 | 0 | 0.5 a metre | 1 (LTS 4 and Avoid both count 1) |
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
| Map colour and dash, painted-lane hiding (drawing) | lower level | lower level | lower level (lane drawn) | lower level (lane hidden, as LTS 4) |

The junction values are base costs. The speed, lane, volume and rural factors and the
cap apply afterwards, as for whole levels, and the orange and red thresholds (600 and
2,000 ft) are unchanged. Junctions read 4.5 like 4 (tier 5 is 4 there).

### Parked

GEOMETRIC-LTS-model.md proposed one geometric rule, `M = r^(L-2)` with `r` set by the
slider, and geometric means for half steps (460.2, 460.7). Owner decision 461 did not
adopt it ("keep what we have currently"), and 461a replaced the geometric mean with
midpoints. It is parked, with its owner questions.

## 4. The rolling stress score (460.12, 461b, 461c) **planned**

The owner, 460.12: "A chart of rolling traffic stress makes more sense than a strip.
That way, spikes show up." 461c: build it from the costs the routing already charges.

### Definition

Along a route of preset P, for a window of length `w` centred on the point at distance
`x`:

    R(x) = ( sum over segments in the window of  metres x M_P(stress) )
         + ( sum over junctions in the window of  cost_m x weight_P )
         + ( sum over Avoid entries in the window of  entry_m )
         ------------------------------------------------------------
                                   w

- `M_P(stress)` is the multiplier above, half steps as midpoints. For a chart one value
  per level is needed, so the proposal is the middle of each range (Default: LTS 3 = 4.3,
  LTS 4 = 14.3; Group 2.4 and 5.8; Fast 1.29 and 2.23; Cargo with passengers 5.0 and 17.5;
  Trailmaxxing 6 and 11; Mass Ride 1). A later refinement could compute each segment's
  value from its own speed and lanes (`road_speed_mph`, `road_lanes`).
- `cost_m` is the junction model's cost (`intersections.cost_of`, after factors, merges
  and the cap) in metres. `weight_P` is the intersection weight at the preset's
  position. At the top of the slider, the worth rule's exchange applies instead: a red
  junction counts 5 x 2 x its cost, an orange one 5 x 1, an unflagged one 0
  (`stress_weight_m`, `refine.py:428-441`).
- `entry_m` is Avoid's entry charge in quiet metres, counted at the point the route
  enters the Avoid stretch.
- The scale matches the multiplier. **1.0 is calm riding**, and higher is more stress.
  Calm metres per metre, or calm miles per mile.
- A route shorter than the window uses its whole length.

### Words as a guide

The band boundaries are the half-step multipliers, so the words follow the same
midpoints. For Default (70):

| R | Words (road panel, 441l) |
|---|---|
| under 2.65 (the 2.5 midpoint) | Comfortable for everyone / Fine for adults (LTS 1-2) |
| 2.65 to 9.3 (the 3.5 midpoint) | For experienced cyclists (LTS 3) |
| 9.3 and up | High stress: busy, fast traffic (LTS 4) |
| a window with an Avoid entry or Avoid metres | Avoid |

Each preset's own multipliers give its own boundaries. Junctions also keep their own
marker at their point in today's orange or red, so averaging never hides a very
high-stress crossing. A screen reader gets a text summary: the highest window, where it
is, and what is in it.

### Window and blend: two options

**Option A, spread over the window (recommended).** A junction's cost counts in full in
every window that contains it. The spike is a plateau one window wide, with height
`1 + cost / w` above the background. It is symmetric, it uses one window for roads and
junctions alike, and it reads directly as "this 0.1 mi costs R times calm riding".

**Option B, short decay.** Roads are averaged over the window as in A. A junction's cost
is instead spread over the distance ridden after it, decaying exponentially with length
`λ`: `cost / λ x e^(-(x - x_j)/λ)`. The area is the same as in A. The peak is sharper,
its height depends on the choice of `λ`, and it falls only after the junction.

Proposed default window: **0.1 mi [161 m], length-weighted.** Owner to confirm the window
and the blend.

### Worked example (Default, made-up route, 0.5 mi [805 m])

| From - to (mi) | What | M or cost |
|---|---|---|
| 0.00-0.20 | LTS 2 street | 1 |
| 0.20-0.25 | LTS 3 street, 0.05 mi [80 m] | 4.3 |
| 0.25-0.50 | LTS 1 street | 1 |
| at 0.35 | Straight across an LTS 4 road from a stop: 35 mph (x1.0), 2 lanes each way (x1.1), no count | 3,000 x 1.1 = 3,300 ft [1,006 m], red; weight 1.0 at 70 |

Window 0.1 mi [161 m]:

| Window centred at | Option A | Option B (λ = 0.025 mi [40 m]) |
|---|---|---|
| 0.10 mi | 1.0 | 1.0 |
| 0.225 mi (holds all the LTS 3) | (40 + 80 x 4.3 + 40) / 161 = **2.65**, LTS 3 words | 2.65 |
| 0.30 to 0.40 mi | (161 + 1,006) / 161 = **7.25**, a plateau 0.1 mi wide, red marker at 0.35 | 1.0 before 0.35 |
| just after 0.35 mi | 7.25 | 1 + 1,006 / 40 = **26** |
| 0.375 mi (40 m on) | 7.25 | 1 + 25 x e^-1 = 10.2 |
| 0.40 mi (80 m on) | 7.25 | 1 + 25 x e^-2 = 4.4 |
| 0.45 mi (161 m on) | 1.0 | 1.5 |

The LTS 3 stretch, shorter than the window, shows at 2.65, under its own 4.3. The plateau
is therefore labelled with what it holds ("0.05 mi of LTS 3"). A plain step line of the
stress number can be drawn faintly behind the score, so a short stretch is still seen at
its true level.

**Recommendation: option A** with a 0.1 mi window, plus the junction markers and the
faint step line. All of section 4 is **planned. Owner to confirm the window and the
blend.** Two questions are also open: Mass Ride's chart (its routing charges no
junction cost; the proposal is to show the model's cost at weight 1, labelled "not used
to choose the route"), and 4.5's entry charge (section 3).
