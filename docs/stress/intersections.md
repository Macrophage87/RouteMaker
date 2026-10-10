# The intersection model

[Index](README.md). Sources: [literature.md](literature.md). This page describes how
RouteMaker prices a junction on a route, as the code is on this branch
(`src/routemaker/intersections.py`, cited below as `:N`; other files are named in full).
The numbers are "option C" (owner decisions 467, 468 and 468a), with the statutory
default speeds of decisions 469 and 469a and the time-of-day bands of decisions 469c to
469e. Section 9 lists what is still open.

Every cost is given first in **calm miles** (a mile of quiet-street riding, 5,280 ft),
with kilometers in brackets (decision 467). The code's own unit is feet of equivalent
quiet-street riding (`Event.cost_ft`), so the feet follow the kilometers in the brackets
(`calm_miles`, `:587-589`). The `calm_mi` and `calm_km` on each of the answer's
`intersections` rows are the junction's own cost, without the preset's weight (decision
469b; `src/core/routing.py:1692-1695`). The rolling stress chart counts a junction at its
cost times the intersection weight at the ride's slider position (section 8;
`junction_m`, `src/routemaker/calm.py:153-161`; [stress-number.md](stress-number.md),
section 4).

## 1. Why it is not in the graph

Valhalla's bicycle costing (3.9.1, as 3.5.1 and 3.6.3 before it) cannot tell which road is crossed or which way the
rider turns. So the model runs on the traced route, where every road's tier at every
junction, the movement and Valhalla's own control flags are known (`:11-22`). One
function gives two outputs. The first is a cost, which the router's choice between
candidate routes weighs. The second is a severity (orange or red), which the planner
draws as a marker on the route.

## 2. Which roads count

A junction costs something only if it involves a **busy road**, meaning tier 3 or
higher (`BUSY_TIER = 3`, `:60`). Where two neighborhood streets (LTS 1 or 2) meet,
nothing is charged. `cost_of` gives a stop sign or an all-way stop there a token 0.002
calm mi [3 m; 10 ft] (`NEIGHBOURHOOD_STOP_FT`, `:91`, used at `:571-574`), but such a
junction makes no event (`assess`, `:700-701`), and a route's junction cost is the sum of
its events (`penalty_m`, `:1078-1080`). So it is never charged to a route and never
drawn. This rests on the owner's account that DC law lets a bicycle roll through a stop
sign when it is safe. Tier 5 (Avoid) is priced as tier 4: every table gives tier 5 the
tier 4 value (`:70`, `:76`, `:216`, `:233`, `:238`), and the severe tier of section 3
takes both (`SEVERE_MIN_TIER = 4`, `:151`).

## 3. Crossing a busy road, from the stopped side

The big cost is waiting at a stop sign, or at no control at all, to cross free-flowing
traffic (`crossing_ft`, `:465-482`). The base cost depends on the crossed road's tier
(`STOPPED_CROSSING_FT`, `:70`). Both are the top of the published ranges (decision 468):

| Crossed road | Base |
|---|---|
| LTS 3 | 0.30 calm mi [0.49 km; 1,600 ft] |
| LTS 4 or Avoid | 0.76 calm mi [1.22 km; 4,000 ft] |

The base is then multiplied by factors for the crossed road (`scale`, `:433-457`). An
input that is not known counts as 1.0, except the speed, as the last bullet says.

- Speed limit (`SPEED_FACTORS`, `:129-130`): 0.8 up to 25 mph [40 km/h], 0.9 up to 30
  mph [48 km/h], 1.0 up to 35 mph [56 km/h], 1.1 up to 40 mph [64 km/h], 1.2 up to 45
  mph [72 km/h], and 1.3 above that.
- Lanes in each direction (`LANE_FACTORS`, `:133-134`): 1.0 for one, 1.1 for two, 1.25
  for three or more.
- Traffic count (`VOLUME_FACTORS`, `:136-137`): 0.85 up to 5,000 vehicles a day, 0.95 up
  to 10,000, 1.05 up to 20,000, and 1.2 above that.
- Rural (`RURAL_SPEED_MPH`, `RURAL_FACTOR`, `:140-141`; applied at `:446-449`): a speed
  of 45 mph [72 km/h] or more, crossed from the stopped side, is taken as rural and
  multiplied by a further 1.25. A speed the map does not give, read inside a Census urban
  area, never counts as rural (`:446-447`).
- **The severe tier** (`:143-155`): an LTS 4 or Avoid road scales more steeply. The speed
  factors are 1.2 up to 40 mph [64 km/h], 1.4 up to 45 mph [72 km/h] and 1.6 above that,
  in place of 1.1, 1.2 and 1.3 (`SEVERE_SPEED_FACTORS`, `:152-153`). The lane factors
  are 1.25 for two lanes in each direction and 1.6 for three or more
  (`SEVERE_LANE_FACTORS`, `:154-155`). The rural factor applies to a left off the road
  as well (section 5; `:448`). A signal, an all-way stop or the priority side is not
  scaled at all (`:472-481`), so in practice the severe tier prices unsignalized
  junctions. It is above anything the literature gives: it is the owner's weighting of
  the worst junctions (decision 467).
- **A road with no mapped speed** (`cost_speed`, `:417-425`) is read at its
  jurisdiction's statutory default (decisions 469 and 469a; `Road.default_speed_mph`,
  `:309-312`, from `statutory_default_mph`, `src/routemaker/stress.py:243-255`): the
  District 20 mph [32 km/h] (alleys 15 mph [24 km/h]); Maryland 30 mph [48 km/h] in an
  urban area (35 mph [56 km/h] divided) and 50 mph [80 km/h] elsewhere (55 mph [89 km/h]
  divided); Virginia 25 mph [40 km/h] in an urban area, 55 mph [89 km/h] elsewhere and 35
  mph [56 km/h] unpaved (`src/routemaker/stress.py:223-241`). Where the state is not
  known, the classifier's own assumed speed is used (`src/routemaker/stress.py:1190`). On
  a segment table built before that column, an LTS 4 or Avoid road with no speed is read
  at 45 mph [72 km/h], decision 468's stopgap (`UNKNOWN_SPEED_SEVERE_MPH`, `:164`), and
  any other unposted road at none. This is for the cost only. The words on the marker
  only ever say what the map gave (`describe_road`, `:635-651`), and an assumed speed is
  never said to a rider.

The result is capped at **2.00 calm mi [3.22 km; 10,560 ft]** (`MAX_CROSSING_FT`,
`:168`; decision 467: "There's definitely intersections that I'd detour 2 miles to
avoid, though rare."). Before the time of day (section 7), a stopped crossing of an LTS 3
road costs about 0.21 to 0.74 calm mi [0.33 to 1.19 km; 1,088 to 3,900 ft], and a
stopped crossing of an LTS 4 road about 0.52 to 2.00 calm mi [0.83 to 3.22 km; 2,720 to
10,560 ft].

## 4. Other controls and sides

| Situation | Cost | Code |
|---|---|---|
| A signal, crossing LTS 3 / LTS 4 or Avoid | 0.03 / 0.11 calm mi [0.05 / 0.18 km; 150 / 600 ft] | `:76`, `:472-473` |
| An all-way stop | 0.014 calm mi [23 m; 75 ft] | `:80`, `:474-475` |
| The priority side: the cross traffic faces the stop sign, or, with no control, the rider's road is the busier one | 0.005 calm mi [8 m; 25 ft] | `:85`, `:476-481` |
| A straight crossing at a mapped trail crossing with no signal mapped | the stopped-side cost times 0.5, and never drawn red (orange at most) | `:104`, `:110`, `:553-554`, `:740-741` |
| A divided road, its two carriageways crossed as one crossing | the costlier carriageway's cost times 0.75 (credit for the median refuge) | `:123`, `:797-814` |

## 5. Movements

- **Onto a busy road** (`MOVEMENT_FACTOR_ONTO`, `:204`; applied at `:535-549`): the
  crossing cost for the junction's own control, times 1.5 for a left, 1.0 for straight
  on, and 0.1 for a right, capped at 2.00 calm mi. The crossing cost is the one
  `crossing_ft` gives: the stopped-side cost of section 3, or the signal, all-way stop or
  priority-side cost of section 4. This applies when the rider comes from a quieter road.
  It also applies when the rider turns off one busy road onto a busier one, or turns with
  a stop sign on their own approach.
- **A left off a busy road**, where the rider on the busy road turns across its oncoming
  traffic (`left_from_ft`, `:498-510`). The oncoming part is 0.15 calm mi [0.24 km; 800
  ft] for LTS 3 and 0.76 calm mi [1.22 km; 4,000 ft] for LTS 4 or Avoid
  (`LEFT_ACROSS_ONCOMING_FT`, `:216`): a left off an unsignalized LTS 4 road costs as
  much as crossing it from a stop (decision 468). It is multiplied by the same speed, lane
  and count factors. The rural factor counts here only on an LTS 4 or Avoid road (the
  severe tier). A one-way road has no oncoming part, though the merge below still counts.
  At a signal the oncoming part is multiplied by 0.4 (`SIGNALISED_LEFT_FACTOR`, `:217`).
- **The merge before a left** (`merge_ft`, `:485-495`), priced only as part of a left
  off a busy road (`:507`), and priced by the road (decision 468): 0.15 calm mi [0.24 km;
  792 ft] for each lane the rider must cross on an LTS 3 road, and 0.30 calm mi [0.48 km;
  1,584 ft] for each lane on an LTS 4 or Avoid road (`MERGE_MILES_PER_LANE`, `:233`). The
  lanes crossed are the road's lanes in one direction, minus one. Where the lane count is
  not known, the road is read as 1 lane (LTS 3) or 2 lanes (LTS 4 or Avoid)
  (`ASSUMED_LANES`, `:238`). On a fast road the merge rises by the severe speed factors,
  never below 1: 1.2 up to 40 mph [64 km/h], 1.4 up to 45 mph [72 km/h] and 1.6 above
  that (`:234`, `:490-493`). So a two-lane merge and then a left on a fast LTS 4 road
  reaches the 2.00 calm mi cap. Away from a signal the merge is not capped at the box turn
  (decision 469b); only the 2.00 calm mi cap applies (`:495`, `:510`).
- **The box-turn cap** (`BOX_TURN_CAP_FT`, `:235`; applied at `:495`, `:508-509` and
  `:706-709`): at a signal, the whole left, oncoming part and merge together, never costs
  more than 0.14 calm mi [0.23 km; 750 ft]. That is the price of the two-stage box turn
  the rider can make instead. The cap is applied again after the time of day (section 7),
  so rush hour never lifts a signalized left above it. Away from a signal the whole left
  is capped only at 2.00 calm mi.
- **A right off a busy road**: 0.003 calm mi [5 m; 15 ft], since it is only slowing down
  (`RIGHT_FROM_BUSY_FT`, `:218`; `:533-534`).
- **A left across a busy road, from one quiet street to another**: the crossing cost
  times 1.5, capped at 2.00 calm mi (`:562-565`).

## 6. Slip lanes

Crossing the path of a free-flowing channelized right-turn lane costs 0.19 calm mi [0.30
km; 1,000 ft] (`SLIP_LANE_FT`, `:250`), and half that, 0.09 calm mi [0.15 km; 500 ft], at
a signal (`SIGNALISED_SLIP_FACTOR`, `:251`; `slip_ft`, `:513-514`). It counts only where
the route crosses the channel's path, not where it rides straight past it, and only
where a busy road meets there (`:566-570`).

## 7. Time of day, combining, severity and the avoidance trigger

- **Time of day** (`time_factor`, `:170-196`; applied in `assess`, `:702-705`): a
  junction with a busy road is multiplied by a factor for the plan's ride time (`when`,
  `src/routemaker/ridetime.py:39-48`). Weekday rush hours, 7 to 10 AM and 4 to 7 PM, are
  x1.25. Other weekday hours, to 9 PM, are x1.0. Weekend daytime, federal holidays
  included, is x0.85. Night, 9 PM to 7 AM on every day of the week, weekend nights
  included, is x0.5 where the crossed road lies in a Census urban area and x0.85 where it
  does not (decisions 468a and 469c to 469e). A road whose urban flag is not known (a
  segment table built before that column) takes x0.85, the smaller reduction. A plan with
  no ride time takes x1.0. A night plan routes on the standard graph, as a weekday plan
  does (`src/routemaker/ridetime.py:22-24`). Quiet-street stops are not scaled, because
  they make no event. The factored cost is capped at 2.00 calm mi, and a signalized left
  is held at the box-turn cap (section 5). These are typical values, not measured ones.
- A junction takes the **largest** of the costs that apply to it, not their sum (`take`
  in `cost_of`, `:517-575`).
- Events that follow one another no more than 148 ft [45 m] apart along the route are
  combined into one (`merge_nearby`, `:817-847`; `MERGE_WITHIN_M` and `MERGED_SHARE`,
  `:780-781`). This catches a divided road's two carriageways, or a trail crossing beside
  a road junction. Within the group, several crossings of the same road (matched by name)
  count once: the costliest, with the median credit if it is a divided road. The combined
  cost is then the costliest event plus half of each of the others, capped at 2.00 calm
  mi (`:833-835`). Combining never makes the color worse than the worst single event's.
- **Severity** (`ORANGE_MIN_FT` and `RED_MIN_FT`, `:261-262`; `severity_of`,
  `:598-603`): **orange** from 0.15 calm mi [0.24 km; 800 ft], and **red** from 0.55 calm
  mi [0.88 km; 2,900 ft]. The color is read after the time of day, so a rush-hour plan
  has more orange and red junctions and a night plan fewer. A stopped crossing of an LTS 3
  road is orange, or red when the road is fast and wide. A stopped crossing of an LTS 4
  road is red, unless the road is both slow (25 mph [40 km/h] or less) and lightly used
  (5,000 vehicles a day or fewer), when it is orange. A signal is neither, at any hour.
- On **Mass Ride** the color follows the busy road's own tier instead: orange for LTS 3,
  red for LTS 4 or Avoid, and only for crossings, lefts and slip lanes (`assess`,
  `:713-739`). The cost is still the model's.
- **Red is also the avoidance trigger.** RouteMaker's search plans again around the
  approaches to junctions whose cost, after the time of day, is red or more
  (`REFINE_MIN_EVENT_FT = RED_MIN_FT`, `src/core/refine.py:111`; used at
  `src/core/refine.py:740-752`). It does not do this on Mass Ride.
- **The debug list.** `debug_junctions: true` on a route request adds `junctions_debug`
  to the answer (`src/core/api.py:230-237`, `:1111-1112`): every junction event, flagged
  or not, with its cost in feet and calm miles, severity, ride-time factor and whether the
  speed was assumed (`JunctionDebugOut`, `src/core/api.py:531-554`;
  `src/core/routing.py:1703-1729`). It holds only facts about the route.

## 8. The preset's weight

How much of a junction's cost counts depends on the traffic-stress slider: 0.25 at 0,
rising in a straight line to 1.0 at 70 (Default) and staying at 1.0 above that
(`intersection_weight`, `src/core/refine.py:214-219`; `INTERSECTION_WEIGHT_AT_ZERO`,
`src/core/refine.py:148`; `STRESS_DEFAULT_AT = 70`, `src/core/presets.py:232`). Mass
Ride's routing charges no junction cost, because the calm search that adds it does not
run for Mass Ride ([routing-costs.md](routing-costs.md)). The rolling stress chart
([stress-number.md](stress-number.md) section 4) uses the same weight, for every junction
the model charges for, flagged or not (`src/routemaker/calm.py:153-161`, `:219-230`;
the weight is passed in at `src/core/routing.py:2522`). At the top of the slider it
counts the worth rule's exchange instead (red 5 x 2 x the cost, orange 5 x 1, unflagged
0; 10 in place of 5 with a target). Mass Ride has no rolling stress chart.

## 9. Still open

Everything above is built. These points are not settled:

- **The 116-route sample** (decision 468): a new run of the project's 116-route sample,
  with every junction counted, to show the owner before the change is merged. Stephen
  chose to run it after Valhalla 3.9.1 is deployed.
- **The bike box cap** (decision 468): the box-turn cap should also apply to an
  unsignalized left where OpenStreetMap maps a bike box or a two-stage turn box. It is not
  implemented, because the router data does not carry those tags (`:229-232`).
- **The classifier's default speeds** (decision 469): 469 asks that the classifier read
  the same statutory defaults wherever it needs a speed. It does in the District (20 mph
  [32 km/h]). In Maryland's and Virginia's urban areas it still reads the MDOT imputation
  by road class, 25 to 35 mph [40 to 56 km/h] (`MD_VA_URBAN_DEFAULT_MPH`,
  `src/routemaker/stress.py:207-222`), and outside them one table for both states. Moving
  it would change tiers on many roads, so it waits for the owner. Only the junction cost
  reads the statutory figures ([classification.md](classification.md)).
- **Calm miles and "rush hour" in the interface** (decisions 467 and 468a): each
  junction's cost in calm miles, and the words "rush hour" where the time of day raised
  it, are to be shown in the panel and the rolling stress chart. The answer carries the
  calm miles and the debug list carries the factor, but the interface does not show them
  per junction yet. The night factor is to be described generally ("usually calmer at
  night", 469d).
- **Weekend nights**: night applies every day of the week, weekend nights included, as
  built (469c proposed it). Whether a weekend night should route like a weekday night has
  been asked of the owner.

The options report, `INTERSECTION-COSTS-options.md` (2026-10-09, kept with the project's
reports, not in this repository), modeled option C before decision 469 (with 468's 45
mph [72 km/h] stopgap for an unposted road, and no time of day). Its modeling (not
re-checked for this page) expected little change in which route wins. By calm miles, the
winner changed for 1 of 39 origin and destination pairs, because road stretches outweigh
junctions at Default: a junction was a median 8% of a route's calm miles under the
earlier model and 11% under option C. The visible changes are in the rolling stress
chart, which reads each junction's own `cost_ft`, and in the junction markers.
