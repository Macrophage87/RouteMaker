# The intersection model

[Index](README.md). Sources: [literature.md](literature.md). This page describes how
RouteMaker prices a junction on a route, as the code is on this branch
(`src/routemaker/intersections.py`, cited below as `:N`; other files are named in full).
Section 9 is **planned** (owner decisions 467, 468 and 468a) and is not built. Part of
468a is only **proposed**, as section 9 says.

Every cost is given first in **calm miles** (a mile of quiet-street riding, 5,280 ft),
with kilometers in brackets (decision 467). The code's own unit is feet of equivalent
quiet-street riding (`Event.cost_ft`), so the feet follow the kilometers in the brackets.
A junction's calm miles, as the rolling stress chart uses them, are its cost times
the intersection weight at the ride's slider position (section 8; `junction_m`,
`src/routemaker/calm.py:153-160`; [stress-number.md](stress-number.md), section 4).

## 1. Why it is not in the graph

Valhalla's bicycle costing (3.9.1, as 3.5.1 and 3.6.3 before it) cannot tell which road is crossed or which way the
rider turns. So the model runs on the traced route, where every road's tier at every
junction, the movement and Valhalla's own control flags are known (`:11-22`). One
function gives two outputs. The first is a cost, which the router's choice between
candidate routes weighs. The second is a severity (orange or red), which the planner
draws as a marker on the route.

## 2. Which roads count

A junction costs something only if it involves a **busy road**, meaning tier 3 or
higher (`BUSY_TIER = 3`, `:49`). Where two neighborhood streets (LTS 1 or 2) meet,
nothing is charged. `cost_of` gives a stop sign or an all-way stop there a token 0.002
calm mi [3 m; 10 ft] (`NEIGHBOURHOOD_STOP_FT`, `:75`, used at `:438-441`), but such a
junction makes no event (`assess`, `:556`), and a route's junction cost is the sum of its
events (`penalty_m`, `:917-919`). So it is never charged to a route and never drawn. This
rests on the owner's account that DC law lets a bicycle roll through a stop sign when it
is safe. Tier 5 (Avoid) is priced the same as tier 4: every table gives tier 5 the tier 4
value (`:56`, `:60`, `:142`).

## 3. Crossing a busy road, from the stopped side

The big cost is waiting at a stop sign, or at no control at all, to cross free-flowing
traffic (`crossing_ft`, `:338-355`). The base cost depends on the crossed road's tier
(`STOPPED_CROSSING_FT`, `:56`):

| Crossed road | Base |
|---|---|
| LTS 3 | 0.23 calm mi [0.37 km; 1,200 ft] |
| LTS 4 or Avoid | 0.57 calm mi [0.91 km; 3,000 ft] |

The base is then multiplied by factors for the crossed road (`scale`, `:318-330`). An
input that is not known counts as 1.0.

- Speed limit (`SPEED_FACTORS`, `:113-114`): 0.8 up to 25 mph [40 km/h], 0.9 up to 30
  mph [48 km/h], 1.0 up to 35 mph [56 km/h], 1.1 up to 40 mph [64 km/h], 1.2 up to 45
  mph [72 km/h], and 1.3 above that.
- Lanes in each direction (`:117-118`): 1.0 for one, 1.1 for two, 1.25 for three or more.
- Traffic count (`:120-121`): 0.85 up to 5,000 vehicles a day, 0.95 up to 10,000, 1.05
  up to 20,000, and 1.2 above that.
- Rural (`:124-125`): a speed limit of 45 mph [72 km/h] or more, crossed from the stopped
  side, is taken as rural and multiplied by a further 1.25.

The result is capped at **0.85 calm mi [1.37 km; 4,500 ft]** (`MAX_CROSSING_FT`, `:126`).
So a stopped crossing of an LTS 3 road costs about 0.15 to 0.55 calm mi [0.24 to 0.89
km], and a stopped crossing of an LTS 4 road about 0.39 to 0.85 calm mi [0.63 to 1.37
km].

## 4. Other controls and sides

| Situation | Cost | Code |
|---|---|---|
| A signal, crossing LTS 3 / LTS 4 or Avoid | 0.03 / 0.06 calm mi [0.05 / 0.09 km; 150 / 300 ft] | `:60` |
| An all-way stop | 0.014 calm mi [23 m; 75 ft] | `:64` |
| The priority side: the cross traffic faces the stop sign, or, with no control, the rider's road is the busier one | 0.005 calm mi [8 m; 25 ft] | `:69`, `:349-354` |
| A straight crossing at a mapped trail crossing with no signal mapped | the stopped-side cost times 0.5, and never drawn red (orange at most) | `:88-94`, `:418-421` |
| A divided road, its two carriageways crossed as one crossing | the costlier carriageway's cost times 0.75 (credit for the median refuge) | `:107`, `:640-657` |

## 5. Movements

- **Onto a busy road** (`MOVEMENT_FACTOR_ONTO`, `:133`; applied at `:406-416`): the
  crossing cost for the junction's own control, times 1.5 for a left, 1.0 for straight
  on, and 0.1 for a right. The crossing cost is the one `crossing_ft` gives: the
  stopped-side cost of section 3, or the signal, all-way stop or priority-side cost of
  section 4. This applies when the rider comes from a quieter road. It also applies when the
  rider turns off one busy road onto a busier one, or turns with a stop sign on their own
  approach.
- **A left off a busy road**, where the rider on the busy road turns across its oncoming
  traffic (`left_from_ft`, `:365-377`). The oncoming part is 0.11 calm mi [0.18 km; 600
  ft] for LTS 3 and 0.28 calm mi [0.46 km; 1,500 ft] for LTS 4 or Avoid
  (`LEFT_ACROSS_ONCOMING_FT`, `:142`). It is multiplied by the same speed, lane and count
  factors, but not the rural one. A one-way road has no oncoming part, though the merge
  below still counts. At a signal the oncoming part is multiplied by 0.4 (`:143`).
- **The merge before a left** (`merge_ft`, `:358-362`), priced only as part of a left
  off a busy road (`:374`): 0.05 calm mi [0.08 km; 250 ft] for each lane the rider must
  cross to reach the left-turn position. That is the road's
  lanes in one direction, minus one (`:153`). Where the lane count is not known, the road
  is read as 1 lane (LTS 3) or 2 lanes (LTS 4 or Avoid) (`:157`). The merge on its own
  never costs more than 0.09 calm mi [0.15 km; 500 ft], anywhere (`:362`).
- **The box-turn cap** (`BOX_TURN_CAP_FT`, `:154`, applied at `:375-376`): at a signal,
  the whole left, oncoming part and merge together, never costs more than 0.09 calm mi
  [0.15 km; 500 ft]. That is the price of the two-stage box turn the rider can make
  instead. Away from a signal the whole left is capped only at 0.85 calm mi.
- **A right off a busy road**: 0.003 calm mi [5 m; 15 ft], since it is only slowing down
  (`:144`).
- **A left across a busy road, from one quiet street to another**: the crossing cost
  times 1.5, capped at 0.85 calm mi (`:429-432`).

## 6. Slip lanes

Crossing the path of a free-flowing channelized right-turn lane costs 0.15 calm mi [0.24
km; 800 ft] (`SLIP_LANE_FT`, `:168`), and half that at a signal (`:169`). It counts only
where the route crosses the channel's path, not where it rides straight past it, and
only where a busy road meets there (`:433-437`).

## 7. Combining, severity and the avoidance trigger

- A junction takes the **largest** of the costs that apply to it, not their sum (`take`
  in `cost_of`, `:384-442`).
- Events that follow one another no more than 148 ft [45 m] apart along the route are
  combined into one
  (`merge_nearby`, `:660-690`; `MERGE_WITHIN_M` and `MERGED_SHARE`, `:623-624`). This
  catches a divided road's two carriageways, or a trail crossing beside a road junction.
  Within the group, several crossings of the same road (matched by name) count once: the
  costliest, with the median credit if it is a divided road. The combined cost is then
  the costliest event plus half of each of the others, capped at 0.85 calm mi. Combining
  never makes the color worse than the worst single event's.
- **Severity** (`ORANGE_MIN_FT` and `RED_MIN_FT`, `:176-177`; `severity_of`, `:454-459`):
  **orange** from 0.11 calm mi [0.18 km; 600 ft], and **red** from 0.38 calm mi [0.61 km;
  2,000 ft]. A stopped crossing of an LTS 3 road is orange, or red when the road is fast
  and wide. A stopped crossing of an LTS 4 road is red. A signal is neither.
- On **Mass Ride** the color follows the busy road's own tier instead: orange for LTS 3,
  red for LTS 4 or Avoid, and only for crossings, lefts and slip lanes (`assess`,
  `:548-583`). The cost is still the model's.
- **Red is also the avoidance trigger.** RouteMaker's search plans again around the
  approaches to junctions whose cost is red or more (`REFINE_MIN_EVENT_FT = RED_MIN_FT`,
  `src/core/refine.py:111`; used at `src/core/refine.py:740-752`). It does not do this on
  Mass Ride.

## 8. The preset's weight

How much of a junction's cost counts depends on the traffic-stress slider: 0.25 at 0,
rising in a straight line to 1.0 at 70 (Default) and staying at 1.0 above that
(`intersection_weight`, `src/core/refine.py:214-219`; `INTERSECTION_WEIGHT_AT_ZERO`,
`src/core/refine.py:148`; `STRESS_DEFAULT_AT = 70`, `src/core/presets.py:232`). Mass
Ride's routing charges no junction cost, because the calm search that adds it does not
run for Mass Ride ([routing-costs.md](routing-costs.md)). The rolling stress chart
([stress-number.md](stress-number.md) section 4) uses the same weight, for every junction
the model charges for, flagged or not (`src/routemaker/calm.py:153-160`, `:219-230`;
the weight is passed in at `src/core/routing.py:2486`). At the top of the slider it
counts the worth rule's exchange instead (red 5 x 2 x the cost, orange 5 x 1, unflagged
0; 10 in place of 5 with a target). Mass Ride has no rolling stress chart.

## 9. Planned: decisions 467, 468 and 468a

**Planned, not built.** This section follows the project's options report,
`INTERSECTION-COSTS-options.md` (2026-10-09, kept with the project's reports, not in this
repository), and the owner's answers so far. None of it is the model described above.

- **Decision 467**: junction costs are to be shown in calm miles, fractions allowed, US
  first with kilometers in brackets. The scale is to let the worst junctions be worth
  about a 2 mi [3.2 km] detour; today's cap is 0.85 calm mi. The exact values are to be
  modeled on real routes and shown to the owner before routing changes.
- **Decision 468: option C** ("B plus a severe tier"), with lane changes for lefts added.
  - *B*, the top of the published ranges: a stopped crossing 0.30 calm mi [0.49 km; 1,600
    ft] for LTS 3 and 0.76 calm mi [1.22 km; 4,000 ft] for LTS 4; a signalized LTS 4
    crossing 0.11 calm mi [0.18 km; 600 ft]; a left off a busy road 0.15 / 0.38 calm mi
    [0.24 / 0.61 km; 800 / 2,000 ft]; a slip lane 0.19 calm mi [0.30 km; 1,000 ft]; and a
    box-turn cap of 0.14 calm mi [0.23 km; 750 ft].
  - *A severe tier*, for unsignalized LTS 4 or Avoid junctions: steeper speed factors (1.2
    at 40 mph [64 km/h], 1.4 at 45 mph [72 km/h], 1.6 above), steeper lane factors (1.25
    for two lanes in each direction, 1.6 for three or more), the rural factor applied to a
    left off the road as well, and a cap of **2 calm mi [3.2 km; 10,560 ft]** in place of
    0.85 calm mi.
  - *Merges priced by the road*: about 0.15 calm mi [0.24 km] for each lane on LTS 3, and
    about 0.3 calm mi [0.48 km] for each lane on LTS 4, more at 40 mph [64 km/h] and up.
    So merging across two lanes and then turning left on a fast road can reach the severe
    range. The box-turn cap applies at signals and where a bike box or two-stage turn box
    is mapped.
  - Answers adopted from the report's suggestions, since the owner raised no objection:
    orange from 0.15 calm mi [0.24 km] and red from 0.55 calm mi [0.89 km], with red still
    the avoidance trigger; a left off an unsignalized LTS 4 road costs as much as crossing
    it from a stop; and a signalized crossing of a big LTS 4 road costs 0.11 calm mi
    [0.18 km].
  - A road with no mapped speed is read at its jurisdiction's statutory default speed
    (decisions 469 and 469a; 469a gives Virginia's: 55 mph [89 km/h] on most highways,
    25 mph [40 km/h] in business and residence districts), for the junction cost and,
    under 469, wherever the classifier needs a speed (to be reconciled with the
    classifier's own defaults; [classification.md](classification.md)). This replaced
    468's 45 mph [72 km/h] answer, which applied to the junction cost only.
  - Before this is merged: an API debug field that lists every junction, and a new run of
    the 116-route sample with every junction counted, shown to the owner.
- **Decision 468a**: a time-of-day factor on busy-road junction costs, from the ride's
  planned time (or, if none is set, the time the route is planned). The bands were set
  by decisions 469c, 469d and 469e: x1.25 in the existing weekday rush windows, 7 to 10
  AM and 4 to 7 PM; x1.0 at other weekday hours until about 9 PM; x0.85 in weekend
  daytime; and at night, about 9 PM to 7 AM, x0.5 inside urban areas and x0.85 outside
  them. Only one point is still **proposed**: that the night band applies every day of
  the week, weekend nights included (469c). Stops where quiet streets meet are not
  affected. The panel and the rolling stress chart would say "rush hour" in words, and
  the night factor is described generally ("usually calmer at night", 469d). **Planned,
  not built.**

The options report's modeling (not re-checked for this page) expected little change in
which route wins. By calm miles, the winner changed for 1 of 39 origin and destination
pairs, because road stretches outweigh junctions at Default: a junction was a median 8%
of a route's calm miles today and 11% under option C. The visible changes would be in
the rolling stress chart, which is built and reads each junction's own `cost_ft`, so it
follows the new costs when they merge, and in the junction markers.
