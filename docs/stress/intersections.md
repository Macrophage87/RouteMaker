# The intersection model

[Index](README.md). Sources: [literature.md](literature.md). This page describes how
RouteMaker prices a junction on a route, as the code is on this branch
(`src/routemaker/intersections.py`, cited below as `:N`). Section 9 is **planned** (owner
decisions 467, 468 and 468a) and is not built.

Every cost is given first in **calm miles** (a mile of quiet-street riding; 5,280 ft). The
code's own unit is feet of equivalent quiet-street riding (`Event.cost_ft`), so the feet
are given in brackets. A junction's calm miles, as used by the rolling chart, are its cost
times the preset's intersection weight (section 8; [stress-number.md](stress-number.md)).

## 1. Why it is not in the graph

Valhalla 3.5.1's bicycle costing cannot say which road is crossed or which way the rider
turns, so the model runs on the traced route, where every road's tier at every junction,
the movement and Valhalla's own control flags are known (`:1-30`). One function gives two
outputs: a cost, which the router's candidate choice weighs, and a severity (orange or
red), which the planner draws as a marker on the route.

## 2. Which roads count

A junction costs something only if it involves a **busy road**: tier 3 or higher
(`BUSY_TIER = 3`, `:49`). Two neighbourhood streets (LTS 1-2) meeting cost almost nothing:
a stop sign on the rider's approach is 0.002 calm mi [10 ft] and is never drawn
(`NEIGHBOURHOOD_STOP_FT`, `:75`; the owner's account that DC law lets bicycles roll through
when safe). Tier 5 (Avoid) is priced as tier 4 (`_tier`, `:333`).

## 3. Crossing a busy road, from the stopped side

The big cost is the rider waiting at a stop, or with no control, against free-flowing
traffic (`crossing_ft`, `:338`). Base cost by the crossed road's tier
(`STOPPED_CROSSING_FT`, `:56`):

| Crossed road | Base |
|---|---|
| LTS 3 | 0.23 calm mi [1,200 ft] |
| LTS 4 or Avoid | 0.57 calm mi [3,000 ft] |

It is then multiplied by the crossed road's factors (`scale`, `:300-330`); an unknown input
counts as 1.0:

- Speed (`SPEED_FACTORS`, `:113`): 0.8 up to 25 mph [40 km/h], 0.9 to 30, 1.0 to 35, 1.1 to
  40, 1.2 to 45, 1.3 above.
- Lanes per direction (`:117`): 1.0 for one, 1.1 for two, 1.25 for three or more.
- Traffic count (`:120`): 0.85 under 5,000 a day, 0.95 to 10,000, 1.05 to 20,000, 1.2 above.
- Rural (`:124-125`): a posted speed of 45 mph or more, from the stopped side, times 1.25.

The result is capped at **0.85 calm mi [4,500 ft]** (`MAX_CROSSING_FT`, `:126`). A stopped
crossing of an LTS 3 road is therefore about 0.15-0.55 mi, and of an LTS 4 road about
0.39-0.85 mi.

## 4. Other controls and sides

| Situation | Cost | Code |
|---|---|---|
| Signal, LTS 3 / LTS 4 or Avoid | 0.03 / 0.06 calm mi [150 / 300 ft] | `:60` |
| All-way stop | 0.014 calm mi [75 ft] | `:64` |
| Priority side: the rider's road is the busier, or the cross traffic faces the sign | 0.005 calm mi [25 ft] | `:69`, `:347-354` |
| Trail crossing marked on the map, no signal mapped | the stopped-side cost times 0.5, and never drawn red (orange at most) | `:88-94` |
| Divided road, two carriageways crossed as one | the costlier one times 0.75 (a median refuge) | `:107` |

## 5. Movements

- **Onto a busy road from a quieter one** (`MOVEMENT_FACTOR_ONTO`, `:133`): the stopped-side
  crossing cost times 1.5 for a left, 1.0 straight, 0.1 for a right.
- **Left off a busy road** (the rider on the road turns across its oncoming traffic;
  `left_from_ft`, `:365`): 0.11 calm mi [600 ft] for LTS 3, 0.28 [1,500 ft] for LTS 4 or
  Avoid (`LEFT_ACROSS_ONCOMING_FT`, `:142`), times the same speed, lane and count factors
  (not the rural one). Nothing on a one-way road. At a signal the oncoming part is times 0.4
  (`:143`).
- **Merges** (`merge_ft`, `:358`): 0.05 calm mi [250 ft] for each lane the rider must cross
  to reach the left-turn position, per direction, with the road's lanes minus one counted
  (`:153`). Where the lane count is unknown the road is read at 1 lane (LTS 3) or 2 (LTS 4,
  Avoid) (`:157`).
- **Box-turn cap** (`:154`): at a signal the whole left, oncoming and merge together, never
  costs more than 0.09 calm mi [500 ft], the price of the two-stage box turn the rider can
  make instead. Away from signals only the 0.85 mi cap applies.
- **Right off a busy road**: 0.003 calm mi [15 ft], only a deceleration (`:144`).
- **Left across a busy road between two quiet streets**: the crossing cost times 1.5.

## 6. Slip lanes

Crossing the path of a free-flowing channelised right-turn lane is 0.15 calm mi [800 ft]
(`SLIP_LANE_FT`, `:168`), halved at a signal (`:169`). It counts only where the route
crosses the channel's path, not where it rides straight past.

## 7. Combining, severity and the avoidance trigger

- A junction takes the **largest** of its applicable costs, not their sum (`take` in
  `cost_of`, `:384-443`).
- Junctions within 45 m (148 ft) of each other on the same road (a divided road's
  carriageways, a trail crossing beside a road junction) are merged: the worst plus half of
  the others, capped at 0.85 mi (`merge_nearby`, `:660`; `MERGE_WITHIN_M` and
  `MERGED_SHARE`, `:623-624`).
- **Severity** (`:176-177`, `severity_of`, `:454`): **orange** from 0.11 calm mi [600 ft],
  **red** from 0.38 calm mi [2,000 ft]. A stopped crossing of an LTS 3 road is usually
  orange, of an LTS 4 road red, and a signal neither.
- **Red is also the avoidance trigger**: RouteMaker's search re-plans around the approaches
  to junctions of red cost (`REFINE_MIN_EVENT_FT = RED_MIN_FT`, `src/core/refine.py:106`,
  `:702`).

## 8. The preset's weight

How much of the junction cost counts depends on the slider: 0.25 at 0, rising in a line to
1.0 at 70 (Default) and above (`intersection_weight`, `src/core/refine.py:209-214`;
`INTERSECTION_WEIGHT_AT_ZERO`, `:143`; `STRESS_DEFAULT_AT = 70`, `src/core/presets.py:226`).
Mass Ride's routing charges none. The planned rolling stress score
([stress-number.md](stress-number.md) section 4) uses the same weight.

## 9. Planned: decisions 467, 468 and 468a

**Planned, not built.** From `reports/INTERSECTION-COSTS-options.md` (2026-10-09). These
are the proposal and the owner's answers so far, not the model above.

- **Decision 467**: show junction costs in calm miles, and raise the worst ones so that an
  unsignalised left across a fast, wide LTS 4 road can approach a 2 mi detour.
- **Decision 468: option C** ("B plus a severe tier"), plus lane changes for lefts.
  - *B*, the top of the published ranges: stopped crossing 0.30 calm mi [1,600 ft] for LTS 3
    and 0.76 [4,000 ft] for LTS 4; signalised LTS 4 0.11 [600 ft]; left off a busy road
    0.15 / 0.38 [800 / 2,000 ft]; slip lane 0.19 [1,000 ft]; box-turn cap 0.14 [750 ft].
  - *Severe tier*, for unsignalised LTS 4 or Avoid junctions: steeper speed factors (1.2 at
    40 mph, 1.4 at 45, 1.6 above), lane factors (1.25 for two lanes a direction, 1.6 for
    three or more), the rural factor also on a left off the road, and a cap of **2 mi
    [3.2 km]** (10,560 ft) in place of 0.85 mi.
  - *Merges priced by the road*: about 0.15 calm mi per lane on LTS 3, about 0.3 per lane on
    LTS 4, more at 40 mph and up, so a two-lane merge then a left on a fast road can reach
    the severe range. The box-turn cap applies at signals and where a bike box or two-stage
    turn box is mapped.
  - Answers taken: orange from 0.15 mi and red from 0.55 mi (red stays the avoidance
    trigger); a left off an unsignalised LTS 4 road costs as much as crossing it from a
    stop; a rural LTS 4 road with no speed is read as 45 mph for junction cost only, never
    shown; a signalised big LTS 4 crossing 0.11 mi.
  - Before merging: an API debug field listing every junction, and a re-run of the 116-route
    sample with every junction counted, shown to the owner.
- **Decision 468a**: a time-of-day factor on busy-road junction costs, from the ride's
  planned time (or the time of planning): weekday rush hours (6:30-9:30 AM and 3:30-6:30 PM)
  **x1.25**, other weekday daytime x1.0, weekday evenings and nights, weekends and federal
  holidays **x0.85**. Proposed; the owner is to confirm with the sample. Quiet-street stops
  are not affected. The panel and chart say "rush hour" in words.

Expected effect, from the owner's sample: the route that wins by calm miles changed for 1
of 39 origin/destination pairs, because road segments outweigh junctions at Default (a
junction is a median 8% of a route's calm miles today and 11% under C). The visible changes
are in the chart and the markers.
