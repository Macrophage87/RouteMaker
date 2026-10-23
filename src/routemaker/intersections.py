"""The intersection cost model: what a junction on a route costs a rider.

OWNER-DECISIONS items 165 to 169, 171 and 172 (2026-10-01), quoted where each
rule is written. The model has two outputs from one function: a cost in feet of
equivalent quiet-street riding (`Event.cost_ft`), which the router's candidate
choice weighs (`core.routing`), and a severity - orange "higher" or red "very
high" - which the planner draws on the route (item 172, "put markers on
intersections in a route, such as an orange marker for higher stress
intersections and a red one for very high stress intersections").

Why this is not in the graph. Valhalla's bicycle costing (3.5.1 to 3.9.1) has no hook that
knows which road is crossed or which way the rider turns. Measured on the live
standard router (docs/DEVELOPMENT.md, "Intersection costs"): every node costs
the rider 0 to 6 s of transition time whatever the crossed road is (3.7 s
median for crossing a primary or secondary road from a residential street,
signalled or not), a right turn costs more than a left (3.0 s against 0.9 s,
the opposite of item 166), and the only per-node knobs are the gate and border
costs, which are per node and not per movement and are already spoken for. The
tag transform sees one way or one node, never the roads that meet at a node, so
a derived tag could not say "a left across a four-lane road" either. The model
therefore works on the traced route, where the tier of every road at every
junction, the movement and Valhalla's own control flags are all known.

The numbers are "option C" of reports/INTERSECTION-COSTS-options.md, chosen by
the owner on 2026-10-09 (OWNER-DECISIONS 467, 468, 468a). They start from
"Bicycle stress literature in depth" (reports/LTS-literature-review-2.md),
"Crossing penalties by control type and right of way" and "Left turns,
multi-lane merges capped by box turns, and slip lanes" (Broach et al.'s
per-mile values, Eugene's 818 ft per left, Copenhagen's 154 ft left against
62 ft right, Oregon's LTS tables), taken at the TOP of those ranges for the
ordinary tiers. The severe tier (an unsignalised junction with an LTS 4 or
Avoid road: steeper speed and lane factors, a left off the road as dear as a
stopped crossing, a merge priced by the road, a 2 mi cap) is ABOVE anything
the literature gives; it is the owner's choice (467: "There's definitely
intersections that I'd detour 2 miles to avoid, though rare."), not a measured
value. Costs are said in calm miles (`calm_miles`), US units first. Nothing
here is a legal claim; the DC roll-through rule (item 171) is the owner's
account.
"""

from __future__ import annotations

import bisect
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum

from . import ridetime
from .geo import Point, haversine

FEET_PER_METRE = 3.28084
KMH_PER_MPH = 1.609344
FEET_PER_MILE = 5280.0
KM_PER_MILE = 1.609344

# --- Which roads count -----------------------------------------------------

# "an at-grade crossing of an LTS 3+ road" (item 165). Tiers below this are
# neighbourhood streets: "neighbourhood stop signs (LTS 1-2 meeting LTS 1-2) cost
# near zero" (item 171).
BUSY_TIER = 3

# --- Base crossing cost, from the STOPPED side against free-flowing traffic ---
#
# Feet of equivalent quiet-street riding by the crossed road's tier. Literature
# review: LTS 3 800-1,600 ft (Eugene 818 ft; Broach 10-20k ADT 6-10% a mile),
# LTS 4 2,500-3,500 ft (Broach 20k+ ADT, 1,700-3,260 ft). OWNER-DECISIONS 468
# (option C, which is B here) takes the TOP of the range: 1,600 ft = 0.30 calm mi
# for LTS 3; 4,000 ft = 0.76 calm mi for LTS 4 (a little above the top, 3,500 ft).
# The severe tier below then raises LTS 4 further on fast, wide roads.
STOPPED_CROSSING_FT = {3: 1600.0, 4: 4000.0, 5: 4000.0}

# "Much lower penalty for traffic signals" (item 165): 100-200 ft for a signal
# with detection, wider roads on a short phase more. Mostly delay. 468: a
# signalised crossing of a big LTS 4 road is 600 ft = 0.11 calm mi (it was 300 ft);
# LTS 3 stays 150 ft = 0.03 calm mi.
SIGNALISED_CROSSING_FT = {3: 150.0, 4: 600.0, 5: 600.0}

# An all-way stop: Broach's stop 0.5-0.9% a mile (26-48 ft) and Arlington's -1
# give 50-100 ft; the rider is stopped, but so is everyone else.
ALL_WAY_STOP_FT = 75.0

# "if you're on the free-flowing route of traffic and there's a stoplight or
# sign for cross traffic, the penalty is much less than being on the cross
# side" (item 169): 0-50 ft in the review's priority-side rows.
PRIORITY_SIDE_FT = 25.0

# A neighbourhood stop sign: "Don't overpenalize neighborhood roads with stop
# signs though. They rarely cause issue. Also DC law lets bikes roll through if
# safe." (item 171; the owner's account, not legal advice.) Near zero, and never
# flagged.
NEIGHBOURHOOD_STOP_FT = 10.0

# A trail crossing - a mapped crossing way (Valhalla's `pedestrian_crossing`),
# or a path, trail, cycletrack or sidewalk meeting the road at a node of its own
# - is a crosswalk, a beacon or a signal. The router's signal flag is read on
# the road junction's own node or its stop lines a few metres away, which
# `core.junctions` reads up to 30 m along the crossed road; from the Track B
# rebuild a crossing whose signal OSM maps on its crossing node or crossing way
# has the flag too (FOLLOWUP-SIGNAL-DERIVE: `remap.derives_signal`,
# `pipeline.signals`). A trail crossing with no signal flag - a crosswalk, a
# beacon, or a signal mapped nowhere the transform reads - is counted at this
# fraction of the stopped-side cost (docs/OPERATIONS.md, "Intersection costs").
# A PROPOSAL; it never lowers a junction the router says has a signal, which is
# already priced as one.
MARKED_CROSSING_FACTOR = 0.5
# And, whatever its cost, such a crossing is never drawn red: the owner,
# 2026-10-01 (item 185), "Trail crossings whose signal is not mapped cap at
# orange and are labelled 'signal not mapped'" (worded "no signal mapped", as
# every junction with nothing mapped is: one phrase, review r2). The cost still
# counts in full where a route is chosen.
MARKED_CROSSING_MAX_SEVERITY = "orange"

# A divided road's two carriageways are one crossing with a median refuge in
# the middle (item 185: "Divided-road crossings count once, with a median-refuge
# credit"). The rider crosses one direction of traffic at a time and can wait
# in the median, which the Mineta and Oregon crossing tables read as one level
# lower. The costlier carriageway's cost times this: the owner, 2026-10-02 (item
# 196), "x0.75 (Recommended)", against about 0.4 for one level lower by the base
# costs (3,000 to 1,200 ft); 0.75 keeps an unsignalized crossing of a divided
# LTS 4 road red, as the round-1 review read Leland St across Connecticut Ave.
# Only two or more crossings, each of a one-way carriageway of its own way, of
# one road by name (`merge_nearby`): never a turn and a crossing, nor a slip
# lane and a crossing (review r2, SHOULD_FIX 2).
MEDIAN_REFUGE_FACTOR = 0.75

# --- Scaling the base by the crossed road's speed, width and volume ----------
#
# "scaled by the crossed road's stress, speed and volume" (item 165). The tier
# is the base; these move it within a tier. Upper bounds of each band, mph.
SPEED_FACTORS = ((25.0, 0.8), (30.0, 0.9), (35.0, 1.0), (40.0, 1.1), (45.0, 1.2))
SPEED_FACTOR_FASTER = 1.3
# Through lanes per direction on the crossed road: a wider road is a longer
# crossing.
LANE_FACTORS = {1: 1.0, 2: 1.1}
LANE_FACTOR_WIDER = 1.25
# A count is a refinement where there is one; the tier already read it.
VOLUME_FACTORS = ((5_000, 0.85), (10_000, 0.95), (20_000, 1.05))
VOLUME_FACTOR_BUSIER = 1.2
# "especially in rural areas where it's usually a stop sign against free-flowing
# traffic" (item 165). Posted speed at or above this is taken as rural.
RURAL_SPEED_MPH = 45.0
RURAL_FACTOR = 1.25

# --- The severe tier (OWNER-DECISIONS 468, option C) ------------------------
#
# An unsignalised junction with an LTS 4 or Avoid road scales more steeply
# than the ordinary tiers: 1.2 at 40 mph, 1.4 at 45 and 1.6 above (against 1.1,
# 1.2 and 1.3), 1.25 for two lanes a direction and 1.6 for three or more
# (against 1.1 and 1.25), and the rural factor applies to a left off the road
# as well as to a stop against it. The literature does not go this high; this is
# the owner's weighting of the worst junctions (467).
SEVERE_MIN_TIER = 4
SEVERE_SPEED_FACTORS = ((25.0, 0.8), (30.0, 0.9), (35.0, 1.0), (40.0, 1.2), (45.0, 1.4))
SEVERE_SPEED_FACTOR_FASTER = 1.6
SEVERE_LANE_FACTORS = {1: 1.0, 2: 1.25}
SEVERE_LANE_FACTOR_WIDER = 1.6
# An unposted road is priced at its jurisdiction's statutory default
# (OWNER-DECISIONS 469: "use each jurisdiction's statutory default instead"),
# which the classifier already reads it at (`routemaker.stress`: the District's
# 20 mph, Maryland's and Virginia's urban and rural figures) and the segment
# table keeps as `road_default_speed_mph`. For cost only; the words
# (`describe_road`) only ever say what the map gave. On a table built before that
# column, an LTS 4 or Avoid road with no speed is read at 468's stopgap, 45 mph,
# and any other unposted road at none (a factor of 1.0).
UNKNOWN_SPEED_SEVERE_MPH = 45.0

# The most any one junction costs: 10,560 ft = 2.00 calm mi (468; 467: "I'd
# detour 2 miles to avoid"). It was 4,500 ft = 0.85 calm mi. Above the literature.
MAX_CROSSING_FT = 10560.0

# --- Time of day (OWNER-DECISIONS 468a, 469c-469e) -------------------------
#
# "Put some more intersection stress during rush hour too and a little less on
# weekends and off hours" (468a), then "Evenings are probably 1x till about 9.
# Then reduced to about half to 7" (469c), "at least in the city" (469d), and
# x0.85 outside it (469e). A busy-road junction's cost is times this by the
# ride's setting (`routemaker.ridetime`): weekday rush (07-10, 16-19) x1.25,
# weekday off-peak (to 9 PM) x1.0, weekend daytime (federal holidays included)
# x0.85, and night (9 PM-7 AM, any day) x0.5 where the crossed road lies in a
# Census urban area and x0.85 where it does not. A road whose urban flag is not
# known (a table built before `road_urban`) takes the rural x0.85, the smaller
# reduction. Typical values, not a promise. Quiet-street stops are not scaled.
TIME_FACTORS = {
    ridetime.WEEKDAY_RUSH: 1.25,
    ridetime.WEEKDAY_OFFPEAK: 1.0,
    ridetime.WEEKEND: 0.85,
}
NIGHT_URBAN_FACTOR = 0.5
NIGHT_RURAL_FACTOR = 0.85
# An LTS 4 or Avoid road (`severe`) crossed or joined with no signal to stop its
# traffic - a stop or yield sign on the rider's side, or nothing mapped - at weekday
# rush hour, in place of rush hour's x1.25: the rider waits for a gap in peak traffic
# on a multi-lane arterial, and gaps get rare. The owner, 2026-10-23, of an unsignalised
# crossing of Connecticut Ave at Decatur Ave, Kensington, at 7:42 AM: "essentially
# impassable", then "Raise their rush hour weight. That's typically where they are the
# problem." Signals, all-way stops, junctions where the cross traffic stops and LTS 3
# roads keep x1.25 (so a plain unsignalised left onto an LTS 3 road stays orange at
# rush hour, 2026-10-10). A typical value, not measured; MAX_CROSSING_FT still caps it.
UNSIGNALISED_RUSH_FACTOR = 2.0
# And at least this much, whatever the road's speed and lanes, for crossing such a road,
# joining it, or turning left across it: the owner, 2026-10-23, "It's not just time but
# stress here. Most people would rather bike 10 minutes than wait 5 minutes at a busy
# crossing for an opening. There are rarely openings." Ten minutes of quiet riding at
# the Default ride's speed (Valhalla's Hybrid 18 km/h, 11.2 mph): 1.86 calm mi (3.0 km).
UNSIGNALISED_RUSH_MIN_FT = 9840.0
# The kinds that wait for a gap in the busy road's traffic (not a right turn onto it,
# riding along it, or a slip lane).
GAP_WAIT_KINDS = frozenset({"crossing", "left_onto", "straight_onto", "left_across", "left_from"})


def time_factor(
    when: str | None,
    urban: bool | None = None,
    control: Control | None = None,
    severe_road: bool = False,
) -> float:
    """The multiplier on a busy-road junction's cost at a ride time; 1.0 where
    the setting is unknown. At night it depends on `urban`, the crossed road's; at
    rush hour on `control`, the junction's, and `severe_road`, whether the road is
    LTS 4 or Avoid (UNSIGNALISED_RUSH_FACTOR where the rider gives way to such a
    road's traffic and no signal stops it)."""
    if when == ridetime.NIGHT:
        return NIGHT_URBAN_FACTOR if urban else NIGHT_RURAL_FACTOR
    if when == ridetime.WEEKDAY_RUSH and severe_road and control in GIVE_WAY_CONTROLS:
        return UNSIGNALISED_RUSH_FACTOR
    return TIME_FACTORS.get(when or "", 1.0)


# --- Movement (item 166) ----------------------------------------------------
#
# "Make it less of a penalty for right turns and more of one for left. For most
# roads, a right turn might be close to 0." Applied to a turn ONTO a busy road
# from a quieter one: the crossing cost above is for going straight across.
MOVEMENT_FACTOR_ONTO = {"left": 1.5, "straight": 1.0, "right": 0.1}

# A left turn FROM a busy road (the rider on the free-flowing road turns across
# its oncoming traffic): the Oregon vehicular-left table, LTS 3 at one lane to
# cross and LTS 4 beyond. Zero where the road is one-way ("unless it's a
# 1-way", item 133). Lower at a signal, where the left has its own phase. The
# LTS 3 value, 600 ft, is BELOW the literature review's 800-1,600 ft range for
# an LTS 3 crossing (it is a left across one oncoming lane from a lane the
# rider already holds, not a crossing from a stop); an owner question.
# 468: LTS 3 800 ft (0.15 calm mi); and "a left off an unsignalised LTS 4 road
# costs as much as crossing it from a stop", so LTS 4 is the stopped crossing's
# 4,000 ft (0.76 calm mi) before the severe tier's factors, plus the merge.
LEFT_ACROSS_ONCOMING_FT = {3: 800.0, 4: 4000.0, 5: 4000.0}
SIGNALISED_LEFT_FACTOR = 0.4
RIGHT_FROM_BUSY_FT = 15.0

# "having to cross several lanes to get into the left turn can add stress too,
# though box turns are an option" (item 167); "What about having to change lanes
# to make a left? That's very stressful too" (468). Priced by the road crossed,
# per lane merged across, per direction: about 0.15 calm mi (792 ft) a lane on
# an LTS 3 road and about 0.30 calm mi (1,584 ft) a lane on LTS 4 or Avoid,
# rising with speed from 40 mph (the severe tier's speed factors, never below
# 1), so a two-lane merge then a left on a fast LTS 4 road reaches the severe
# range. Not in the literature. At a signal the whole left (oncoming lanes and
# merge together) is capped at a two-stage box turn, 750 ft = 0.14 calm mi
# (items 167, 186, 468). Where OSM maps a bike box or two-stage turn box the same
# cap should apply to an unsignalised left, but the router data does not carry
# those tags (nothing in lua/ or the pipeline reads an advanced stop line or a
# bicycle box), so that cap is not applied.
MERGE_MILES_PER_LANE = {3: 0.15, 4: 0.30, 5: 0.30}
MERGE_SPEED_FLOOR = 1.0
BOX_TURN_CAP_FT = 750.0
# Where the lane count is unknown, a road of this tier is read at this many
# lanes a direction for the merge.
ASSUMED_LANES = {3: 1, 4: 2, 5: 2}

# --- Slip lanes (items 169 and 195) ------------------------------------------
#
# "Sliplanes should get a penalty too": a free-flowing channelised right-turn
# lane crossed as at least an unsignalized LTS 3 crossing, about 800 ft, unless
# a raised crossing is tagged (not read). Halved at a signal. Only where the
# route crosses the channel's path (the owner, 2026-10-02, item 195: "Flag only
# when you cross it (Recommended)"); riding straight past it along the road is
# not. What "crosses" is, from the router's arms at the node, is
# `core.junctions.crossed_links`.
# 468: 1,000 ft = 0.19 calm mi (it was 800 ft).
SLIP_LANE_FT = 1000.0
SIGNALISED_SLIP_FACTOR = 0.5

# --- Severity (item 172) ----------------------------------------------------
#
# A stopped-side crossing of an LTS 3 road (800-1,600 ft) is orange; of an LTS 4
# road (2,500-3,500 ft) red; a left onto or across an LTS 3 road is orange, red
# when the road is fast. A signalized crossing (150-300 ft) is neither.
# 468: orange from 800 ft = 0.15 calm mi, red from 2,900 ft = 0.55 calm mi (they
# were 600 and 2,000 ft), so the mix of markers holds with the higher costs. Red
# is also the search's avoidance trigger (`core.refine.REFINE_MIN_EVENT_FT`).
# 2026-10-10: red from 3,100 ft = 0.59 calm mi [0.94 km], so an ordinary
# unsignalised left onto an LTS 3 road (2,400 ft, x1.25 at rush hour = 3,000 ft)
# stays orange at rush hour. The 468 sample re-run that day: 21 of the 38
# rush-hour orange-to-red changes were this one case, pushed just over 2,900 ft
# by the 1.25 factor. The owner chose this on 2026-10-10
# ("Raise red slightly").
ORANGE_MIN_FT = 800.0
RED_MIN_FT = 3100.0
ORANGE = "orange"
RED = "red"

# How far from straight on is still "straight", and the angle past which it is
# a reversal rather than a turn.
STRAIGHT_MAX_DEG = 35.0

# --- Riders' ratings of a junction (OWNER-DECISIONS 232) ----------------------
#
# "In some times the road is fine, but the intersection can be especially
# dangerous." A rider suggests a danger level for a junction and an instance
# admin approves it (`core.junction_suggestions`): from then on every route
# through that junction pays the level's cost and shows its marker, whatever
# the roads either side make of it, raising or lowering the model's own figure.
# Levels are the poll's (`core.suggestion_post.JUNCTION_WORDS`): 2 easy, 3 takes
# patience, 4 hard. Avoid (5) is not a rating here: it is an Avoid-rated
# junction (`routemaker.avoid_junctions`), with its own penalty and marker.
# The costs are the model's own figures for the matching colour: an all-way
# stop's for easy (no marker), a stopped-side LTS 3 crossing's for orange, an
# LTS 4 crossing's for red. A PROPOSAL, as every number here.
RATING_COST_FT = {2: ALL_WAY_STOP_FT, 3: STOPPED_CROSSING_FT[3], 4: STOPPED_CROSSING_FT[4]}
RATING_SEVERITY = {2: None, 3: ORANGE, 4: RED}
RATING_WORDS = {2: "easy", 3: "takes patience", 4: "hard"}
# A route passes a rated junction where one of its nodes is this close to the
# rating's point (metres): the Avoid junctions' own 49 ft (15 m), which takes in
# a divided road's two carriageway nodes and stays short of the next junction.
RATING_MATCH_M = 15.0


@dataclass(frozen=True)
class Rating:
    """An approved rider rating of one junction: its node and its level (2 to 4)."""

    id: int
    lon: float
    lat: float
    level: int


# --- Flashing beacons mapped as signals ----------------------------------------
#
# The owner, 2026-10-20, at Connecticut Ave (MD 185) and Baltimore St, Kensington: "a
# traffic light that's a blinking red against free flowing traffic. It wasn't
# passable." OSM maps the junction with a signal; MDOT SHA lists the device there as a
# Warning Beacon, not a Traffic Control Signal. A beacon stops nobody on the main road
# (flashing yellow) and tells the side street to stop (flashing red): the junction is a
# two-way stop. So a junction priced as signalised whose node is within BEACON_MATCH_M
# of a known beacon (`core.flashing_signals`: the owner's list and MDOT SHA's beacons)
# is priced with no signal: the busier road keeps priority and the rider crossing it is
# on the stopped side (`crossing_ft`, `Control.NONE`).
#
# The reach in which the junction model takes a signal for the junction's own
# (`trace_junctions.APPROACH_M`, 98 ft): a divided road's far carriageway node, or a
# stop line, within it reads the beacon's flag, so it is the beacon's too.
BEACON_MATCH_M = 30.0


@dataclass(frozen=True)
class Beacon:
    """A known flashing beacon at a junction mapped as signalised."""

    id: int
    lon: float
    lat: float


# BEACON_MATCH_M as degrees of latitude, with room: a cheap test before the distance.
_BEACON_DEG = BEACON_MATCH_M / 100_000.0


def beacons_near(points: Sequence[tuple[float, float]], beacons: Sequence[Beacon]) -> list[Beacon]:
    """The beacons within reach of the box round `points` (lon, lat): a route meets a few
    of a state's beacons at most, so each junction is then matched against those only."""
    if not points or not beacons:
        return []
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    # A degree of longitude is shorter than one of latitude: twice the margin covers 60 N.
    lon_margin = 2 * _BEACON_DEG
    return [
        b
        for b in beacons
        if min(lats) - _BEACON_DEG <= b.lat <= max(lats) + _BEACON_DEG
        and min(lons) - lon_margin <= b.lon <= max(lons) + lon_margin
    ]


def beacon_at(lon: float, lat: float, beacons: Sequence[Beacon]) -> Beacon | None:
    """The beacon nearest (lon, lat) within BEACON_MATCH_M, or None."""
    best, best_m = None, BEACON_MATCH_M
    for beacon in beacons:
        if abs(beacon.lat - lat) > _BEACON_DEG:
            continue
        m = haversine(Point(lon, lat), Point(beacon.lon, beacon.lat))
        if m <= best_m:
            best, best_m = beacon, m
    return best


def rating_at(lon: float, lat: float, ratings: Sequence[Rating]) -> Rating | None:
    """The rating nearest (lon, lat) within RATING_MATCH_M, or None."""
    best, best_m = None, RATING_MATCH_M
    for rating in ratings:
        m = haversine(Point(lon, lat), Point(rating.lon, rating.lat))
        if m <= best_m:
            best, best_m = rating, m
    return best


class Movement(StrEnum):
    LEFT = "left"
    STRAIGHT = "straight"
    RIGHT = "right"


class Control(StrEnum):
    """Who has the right of way at a junction, from the rider's approach."""

    SIGNAL = "signal"
    # The rider's approach faces a stop or yield sign.
    STOP = "stop"
    # The cross traffic faces a stop sign and the rider's road is free-flowing.
    CROSS_STOP = "cross_stop"
    # Stop signs on every approach.
    ALL_STOP = "all_stop"
    # Nothing known: no signal and no sign in the data.
    NONE = "none"


# The controls where the rider gives way to traffic no signal stops (`time_factor`).
GIVE_WAY_CONTROLS = frozenset({Control.STOP, Control.NONE})


@dataclass(frozen=True)
class Road:
    """What the model knows about one road at a junction. Everything but the
    tier may be unknown: the segment table has the speed and lanes from the
    first rebuild after this model, and a count only where one reached."""

    tier: int | None
    speed_mph: float | None = None
    lanes: int | None = None  # through lanes per direction
    oneway: bool | None = None
    aadt: int | None = None
    # The road's names as the router has them (lower case), or "way <id>"
    # where it has none: a divided road's two carriageways share them.
    names: frozenset[str] = frozenset()
    # The names as mapped ("MacArthur Boulevard"), for saying; `names` are keys.
    display: tuple[str, ...] = field(default=(), compare=False)
    # The OSM ways of it at the junction (a carriageway's, where it is one).
    ways: frozenset[int] = frozenset()
    # The speed the classifier assumed where none is posted (the jurisdiction's
    # statutory default; `cost_speed`), and whether the road lies in a Census
    # urban area (`time_factor` at night). None on a table built before them.
    default_speed_mph: float | None = field(default=None, compare=False)
    urban: bool | None = field(default=None, compare=False)
    # A half step (OWNER-DECISIONS 441i-441l, 461a): the road is half a level above `tier`.
    # Its base costs are the midpoints of its two levels' (`_table`); an on/off rule
    # takes the cautious side, so 2.5 is busy.
    half: bool = False

    @property
    def level(self) -> float:
        """The tier as a number, half step included (0 where unknown)."""
        if self.tier is None:
            return 0.0
        return self.tier + (0.5 if self.half and self.tier < 5 else 0.0)

    @property
    def busy(self) -> bool:
        return self.tier is not None and self.level >= BUSY_TIER - 0.5


@dataclass(frozen=True)
class Junction:
    """One node of the traced route, with the roads that meet there."""

    m: float
    lon: float
    lat: float
    movement: Movement
    incoming: Road
    outgoing: Road
    crossed: tuple[Road, ...] = ()
    control: Control = Control.NONE
    # The route crosses a slip lane's path here (item 195; which movements do
    # is `core.junctions.crossed_links`).
    slip_lane: bool = False
    # The route crosses by a mapped crossing way (a trail crossing a road).
    marked_crossing: bool = False
    # The route arrives or leaves on a path, trail, cycletrack or sidewalk.
    path_crossing: bool = False
    # A point on the edge the route arrives by, which a re-plan excludes to
    # make the router approach another way (`core.refine`).
    approach: tuple[float, float] | None = None
    # The turn channels and ramps that join here (other than the route's own).
    links: tuple[Road, ...] = ()
    # Whether the router's answer for the node was found (`core.junctions`);
    # where it was not, nothing crosses and the control is unknown.
    located: bool = True
    # The rider goes straight on and stays on the same road: the same way, or
    # a way with a name in common. Its tier changing here is not "joining" it
    # (review r2, SHOULD_FIX 1).
    continues: bool = False
    # An approved rider rating of the junction (`Rating.level`, 2 to 4), which
    # sets its cost and colour (OWNER-DECISIONS 232); None: the model's own.
    rating: int | None = None
    # The map has a signal here, but it is a flashing beacon (`with_beacons`): priced
    # with no signal, and said so.
    beacon: bool = False


@dataclass(frozen=True)
class Event:
    """A junction that costs the rider something, and what to tell them."""

    m: float
    lon: float
    lat: float
    kind: str
    movement: Movement
    control: Control
    cost_ft: float
    severity: str | None
    reason: str
    crossed_tier: int | None
    # Never drawn: below the flag thresholds, or a neighbourhood stop.
    flagged: bool
    approach: tuple[float, float] | None = None
    # A Mass Ride's colour is the road's tier, which a merge leaves alone.
    group_severity: bool = False
    # The road the event is about (its names), for counting a divided road's
    # two carriageways once (`merge_nearby`).
    road_names: frozenset[str] = frozenset()
    # The same names as mapped ("MacArthur Boulevard"), in the router's order:
    # for saying, where `road_names` are lower-case keys for matching.
    road_display: tuple[str, ...] = field(default=(), compare=False)
    # The most this event may be drawn as, whatever its cost (a marked
    # crossing with no signal mapped: orange, item 185).
    max_severity: str | None = None
    # The road's ways at the junction and whether it is one-way there: a
    # divided road's two carriageways are two one-way roads of different ways
    # with a name in common (`merge_nearby`).
    road_ways: frozenset[int] = frozenset()
    road_oneway: bool | None = None
    # A divided road's carriageways crossed as one (`_one_road`): each is one-way, but
    # the road has two approaches to hold, so a Mass Ride's corkers count it as two-way
    # (PLAN item 139). `road_oneway` keeps its meaning for the junction costs.
    road_divided: bool = False
    # A Mass Ride's signalized crossings that run within GROUP_WITHIN_M of one
    # another are one group, numbered from 1 in route order (`number_groups`;
    # items 233 and 234). None: not in a group, and always None off a Mass Ride.
    group: int | None = None
    # The riders' rating that set this event's cost and colour (2 to 4), or None.
    rating: int | None = None
    # The cost read a speed the map did not give (the statutory default, or the
    # 45 mph stopgap; `cost_speed`): for the debug list; never said to a rider.
    assumed_speed: bool = field(default=False, compare=False)
    # The ride-time factor that was applied (`time_factor`, 468a, 469c-469e).
    time_factor: float = field(default=1.0, compare=False)
    # The road's through lanes per direction there, where known (`Road.lanes`): a Mass
    # Ride's corkers hold one an approach lane where no signal holds the cross traffic
    # (PLAN item 139's per-lane rule; the chart counts them, `corkersFor`).
    road_lanes: int | None = field(default=None, compare=False)
    # The ride's setting (`routemaker.ridetime`: "weekday_rush", "weekend" or
    # "night") where it changed this event's cost, so the planner can say so in
    # words (468a: "rush hour"); None where the cost is the hour-free one: off-peak,
    # no setting, a cap that held either way, a quiet-street stop or a rated junction.
    time_band: str | None = field(default=None, compare=False)
    # The cost this event would have with no ride time (same caps), or None where it
    # is `cost_ft`: carried through a refuge credit and a merge, so a merged event
    # names the ride time only where the hour moved the merged cost too.
    untimed_ft: float | None = field(default=None, compare=False)
    # The junction's mapped signal is a flashing beacon (`Junction.beacon`).
    beacon: bool = field(default=False, compare=False)


def _untimed(event: Event) -> float:
    return event.cost_ft if event.untimed_ft is None else event.untimed_ft


def movement_of(heading_in: float, heading_out: float) -> Movement:
    """Left, straight or right, from the compass heading the rider arrives on
    and the one they leave on. A right turn is a clockwise change."""
    turn = (heading_out - heading_in + 540.0) % 360.0 - 180.0
    if abs(turn) <= STRAIGHT_MAX_DEG:
        return Movement.STRAIGHT
    return Movement.RIGHT if turn > 0 else Movement.LEFT


def _band(value: float, bands: tuple[tuple[float, float], ...], above: float) -> float:
    for limit, factor in bands:
        if value <= limit:
            return factor
    return above


def severe(road: Road) -> bool:
    return (road.tier or 0) >= SEVERE_MIN_TIER


def cost_speed(road: Road) -> float | None:
    """The speed the cost reads: the map's, else the jurisdiction's statutory
    default (469, `Road.default_speed_mph`), else for an LTS 4 / Avoid road the
    stopgap 45 mph. For cost only; never said."""
    if road.speed_mph is not None:
        return road.speed_mph
    if road.default_speed_mph is not None:
        return road.default_speed_mph
    return UNKNOWN_SPEED_SEVERE_MPH if severe(road) else None


def speed_assumed(road: Road) -> bool:
    """Whether the cost read a speed the map did not give (`cost_speed`)."""
    return road.speed_mph is None and cost_speed(road) is not None


def scale(road: Road, stopped_side: bool) -> float:
    """The crossed road's speed, width, volume and rurality, as a multiplier on
    the tier's base cost. Unknown inputs are 1.0, not guessed, except an LTS 4 /
    Avoid road's speed (`cost_speed`). The severe tier (LTS 4, Avoid) scales
    more steeply and counts rurality on any movement (468)."""
    hard = severe(road)
    factor = 1.0
    speed = cost_speed(road)
    if speed is not None:
        if hard:
            factor *= _band(speed, SEVERE_SPEED_FACTORS, SEVERE_SPEED_FACTOR_FASTER)
        else:
            factor *= _band(speed, SPEED_FACTORS, SPEED_FACTOR_FASTER)
        # A speed the law assumes is no sign of a rural road inside a town.
        rural = road.speed_mph is not None or road.urban is not True
        if (stopped_side or hard) and speed >= RURAL_SPEED_MPH and rural:
            factor *= RURAL_FACTOR
    if road.lanes is not None:
        if hard:
            factor *= SEVERE_LANE_FACTORS.get(road.lanes, SEVERE_LANE_FACTOR_WIDER)
        else:
            factor *= LANE_FACTORS.get(road.lanes, LANE_FACTOR_WIDER)
    if road.aadt is not None:
        factor *= _band(float(road.aadt), VOLUME_FACTORS, VOLUME_FACTOR_BUSIER)
    return factor


def _tier(road: Road) -> int:
    """The tier a busy road's table is read at (4 stands for 5 as well)."""
    return min(max(road.tier or BUSY_TIER, BUSY_TIER), 5)


def _table(table: dict[int, float], road: Road) -> float:
    """A busy road's base value from a table by tier. A half step takes the midpoint of
    its two levels' values (461a: 2.5 is half of LTS 3's, since LTS 2 costs nothing
    here; 3.5 between LTS 3's and LTS 4's; 4.5 as LTS 4, which equals Avoid's here)."""
    if road.half and road.tier is not None and 2 <= road.tier <= 4:
        low = table.get(road.tier, 0.0) if road.tier >= BUSY_TIER else 0.0
        return (low + table[min(road.tier + 1, 5)]) / 2
    return table[_tier(road)]


def crossing_ft(road: Road, control: Control, rider_tier: float | None) -> float:
    """Straight across `road` (busy) from the rider's road.

    The big cost is the STOPPED side against free-flowing traffic; at a signal
    it is much lower; on the free-flowing road, through a junction where the
    cross traffic stops, it is small (items 165 and 169)."""
    if control is Control.SIGNAL:
        return _table(SIGNALISED_CROSSING_FT, road)
    if control is Control.ALL_STOP:
        return ALL_WAY_STOP_FT
    # The rider's own road has priority: it is the busier road, or the cross
    # traffic is the one facing the sign.
    if control is Control.CROSS_STOP:
        return PRIORITY_SIDE_FT
    if control is Control.NONE and rider_tier is not None and rider_tier > road.level:
        return PRIORITY_SIDE_FT
    return min(_table(STOPPED_CROSSING_FT, road) * scale(road, stopped_side=True), MAX_CROSSING_FT)


def merge_ft(road: Road, control: Control = Control.NONE) -> float:
    """Lanes the rider must cross to reach the left-turn position, priced by the
    road (468): per lane, by tier, rising with speed from 40 mph. At a signal
    capped at a box turn (item 167). `road.lanes` is lanes per direction."""
    lanes = road.lanes if road.lanes is not None else ASSUMED_LANES.get(_tier(road), 1)
    speed = cost_speed(road)
    rise = MERGE_SPEED_FLOOR
    if speed:
        rise = max(rise, _band(speed, SEVERE_SPEED_FACTORS, SEVERE_SPEED_FACTOR_FASTER))
    feet = max(lanes - 1, 0) * MERGE_MILES_PER_LANE[_tier(road)] * FEET_PER_MILE * rise
    return min(feet, BOX_TURN_CAP_FT) if control is Control.SIGNAL else feet


def left_from_ft(road: Road, control: Control) -> float:
    """A left turn off a busy road: across its oncoming lanes (none on a
    one-way) and over its other lanes to the left-turn position. At a signal
    never more than the box turn the rider can make instead (item 186)."""
    oncoming = 0.0 if road.oneway else _table(LEFT_ACROSS_ONCOMING_FT, road)
    if oncoming:
        oncoming *= scale(road, stopped_side=False)
        if control is Control.SIGNAL:
            oncoming *= SIGNALISED_LEFT_FACTOR
    total = oncoming + merge_ft(road, control)
    if control is Control.SIGNAL:
        total = min(total, BOX_TURN_CAP_FT)
    return min(total, MAX_CROSSING_FT)


def slip_ft(control: Control) -> float:
    return SLIP_LANE_FT * (SIGNALISED_SLIP_FACTOR if control is Control.SIGNAL else 1.0)


def cost_of(junction: Junction) -> tuple[float, str, Road | None]:
    """The cost in feet of one junction, what kind it is, and the busy road it
    is about (None for a neighbourhood junction)."""
    j = junction
    cost, kind, about = 0.0, "neighbourhood", None

    def take(value: float, label: str, road: Road | None) -> None:
        nonlocal cost, kind, about
        if value > cost:
            cost, kind, about = value, label, road

    if j.incoming.busy and j.movement is not Movement.STRAIGHT:
        # Turning off a busy road: a left crosses its oncoming traffic and its
        # lanes; a right is only a deceleration (item 166).
        if j.movement is Movement.LEFT:
            take(left_from_ft(j.incoming, j.control), "left_from", j.incoming)
        else:
            take(RIGHT_FROM_BUSY_FT, "right_from", j.incoming)
    # A turn off one busy road onto another from the stopped side: onto a
    # busier road, or with a stop or yield sign on the rider's approach (review
    # r1, B3: Flanders Ave, LTS 3 with a stop, left onto Strathmore Ave, LTS 3,
    # is the stopped side's left, 1,800 ft, not the free-flowing side's 600).
    turning_from_busy_onto = (
        j.incoming.busy
        and j.movement is not Movement.STRAIGHT
        and (j.outgoing.level > j.incoming.level or j.control is Control.STOP)
    )
    if j.outgoing.busy and not j.continues and (not j.incoming.busy or turning_from_busy_onto):
        # Entering a busy road from a quieter one, or from the stopped side:
        # the stopped side's crossing cost, by the movement.
        factor = MOVEMENT_FACTOR_ONTO[j.movement.value]
        base = crossing_ft(j.outgoing, j.control, _rider(j.incoming))
        take(min(base * factor, MAX_CROSSING_FT), f"{j.movement.value}_onto", j.outgoing)
    for road in (r for r in j.crossed if r.busy):
        if j.movement is Movement.STRAIGHT:
            value = crossing_ft(road, j.control, _rider(j.incoming))
            if marked_unsignalised(j):
                value *= MARKED_CROSSING_FACTOR
            # On a busy road of its own the rider only meets a side street's
            # conflict: priority side, small (item 169).
            take(
                value,
                "along" if j.incoming.busy and value <= PRIORITY_SIDE_FT else "crossing",
                road,
            )
        elif j.movement is Movement.LEFT and not j.incoming.busy and not j.outgoing.busy:
            # A left from a quiet street across one busy road to a quiet one beyond.
            value = crossing_ft(road, j.control, _rider(j.incoming)) * MOVEMENT_FACTOR_ONTO["left"]
            take(min(value, MAX_CROSSING_FT), "left_across", road)
    if j.slip_lane:
        # About the busiest road the channel leaves or joins.
        roads = [r for r in (j.incoming, j.outgoing, *j.crossed, *j.links) if r.busy]
        busiest = max(roads, key=lambda r: r.level) if roads else None
        take(slip_ft(j.control) if busiest else 0.0, "slip_lane", busiest)
    if about is None and not j.incoming.busy and not j.outgoing.busy:
        # Quiet street meets quiet street: a stop sign here is the owner's
        # "rolls through when safe", priced near zero.
        cost = NEIGHBOURHOOD_STOP_FT if j.control in {Control.STOP, Control.ALL_STOP} else 0.0
    return cost, kind, about


def _rider(road: Road) -> float | None:
    """The rider's road's level for the priority test, half step included."""
    return None if road.tier is None else road.level


def marked_unsignalised(junction: Junction) -> bool:
    """A trail crossing with no signal mapped there (no flag at all, or a stop
    or yield on the rider's side): the route crosses by a mapped crossing way,
    or arrives or leaves on a path, trail, cycletrack or sidewalk (item 185:
    "Trail crossings whose signal is not mapped cap at orange")."""
    trail = junction.marked_crossing or junction.path_crossing
    return trail and junction.control in {Control.NONE, Control.STOP}


def calm_miles(cost_ft: float) -> float:
    """A cost in calm miles (467): feet of quiet riding over 5,280."""
    return cost_ft / FEET_PER_MILE


def calm_text(cost_ft: float) -> str:
    """ "0.55 calm mi (0.88 calm km)": US units first, metric in brackets."""
    miles = calm_miles(cost_ft)
    return f"{miles:.2f} calm mi ({miles * KM_PER_MILE:.2f} calm km)"


def severity_of(cost_ft: float) -> str | None:
    if cost_ft >= RED_MIN_FT:
        return RED
    if cost_ft >= ORANGE_MIN_FT:
        return ORANGE
    return None


# Severities in order, for "no more than" and "the worst of".
_RANK = {None: 0, ORANGE: 1, RED: 2}


def _at_most(severity: str | None, cap: str | None) -> str | None:
    if cap is None or _RANK[severity] <= _RANK[cap]:
        return severity
    return cap


def _worst(severities) -> str | None:
    return max(severities, key=lambda s: _RANK[s], default=None)


def _lanes_total(road: Road) -> int | None:
    if road.lanes is None:
        return None
    return road.lanes if road.oneway else road.lanes * 2


# What a road is called where nothing but its tier is known: the stress map
# legend's own words ("Heavy or fast traffic", "Legal, but best avoided").
TIER_NOUNS = {
    3: "busy road (LTS 3)",
    4: "heavy-traffic road (LTS 4)",
    5: "road best avoided (Avoid)",
}


def describe_road(road: Road | None) -> str:
    """ "4-lane 35 mph (56 km/h) road", or what is known of one. Only what the
    classifier read from the map or an agency is stated: an assumed speed or
    lane count is never stored (`routemaker.stress`), so it is never said."""
    if road is None:
        return "road"
    parts = []
    lanes = _lanes_total(road)
    if lanes:
        parts.append(f"{lanes}-lane")
    if road.speed_mph:
        kmh = round(road.speed_mph * KMH_PER_MPH)
        parts.append(f"{round(road.speed_mph)} mph ({kmh} km/h)")
    if not parts and road.tier in TIER_NOUNS:
        return TIER_NOUNS[road.tier]
    parts.append("road")
    return " ".join(parts)


def _article(text: str) -> str:
    return "an" if text[:1] in "aeiou8" or text.startswith(("11-", "18-")) else "a"


CONTROL_WORDS = {
    Control.SIGNAL: "traffic signal",
    Control.STOP: "stop sign on your side",
    Control.CROSS_STOP: "cross traffic stops",
    Control.ALL_STOP: "all-way stop",
    # Nothing in the data: there may be a signal the map does not have. One
    # wording for road junctions and trail crossings alike: item 185's "signal
    # not mapped" is the same fact, and review r2 asked for one phrase.
    Control.NONE: "no signal mapped",
}
# A junction whose mapped signal is a flashing beacon (`Junction.beacon`).
BEACON_WORDS = "flashing light, not a signal"

KIND_WORDS = {
    "crossing": "Crossing",
    "left_onto": "Left turn onto",
    "right_onto": "Right turn onto",
    "straight_onto": "Joining",
    "left_across": "Left turn across",
    "left_from": "Left turn across",
    "right_from": "Right turn off",
    "along": "Side streets along",
    # The route crosses the slip lane's path (item 195), so the words say so
    # (review r3: "beside" read as riding past it).
    "slip_lane": "Crossing a slip lane off",
}


def reason_of(kind: str, road: Road | None, control: Control, beacon: bool = False) -> str:
    """The sentence a click on the marker shows, in US units first (the
    owner's example: "Left turn across 4-lane 35 mph road, no signal")."""
    noun = describe_road(road)
    words = CONTROL_WORDS[control]
    if beacon:
        # The map's signal is a flashing beacon (`with_beacons`): said in place of "no
        # signal mapped", or beside the signs.
        words = BEACON_WORDS if control is Control.NONE else f"{words}, {BEACON_WORDS}"
    return f"{KIND_WORDS.get(kind, 'Junction with')} {_article(noun)} {noun}, {words}"


def assess(junction: Junction, group: bool = False, when: str | None = None) -> Event | None:
    """The event at one junction, or None where there is nothing to say.

    `group` is the Mass Ride reading (items 133 and 138: "put an orange warning
    icon across any LTS3 intersection and a red one across an LTS4"): the colour
    is the busy road's own tier, orange for LTS 3 and red for LTS 4 or Avoid, and
    a left across a one-way road gets none. The cost is still the model's.

    A junction riders have rated (`Junction.rating`) takes the rating's cost and
    colour on either reading, a neighbourhood junction included (232), except
    that "easy" never costs more than the model's own figure and adds nothing
    where the model has nothing to say."""
    cost, kind, about = cost_of(junction)
    if junction.rating in RATING_COST_FT:
        # "Easy" is held to the model's figure for this hour (468a); a rating's own cost
        # is fixed, as a person set it.
        model = cost
        if kind != "neighbourhood" and about is not None:
            model = min(
                cost * time_factor(when, about.urban, junction.control, severe(about)),
                MAX_CROSSING_FT,
            )
        return rated(junction, kind, about, model, group)
    if kind == "neighbourhood" or about is None:
        return None
    # 468a, 469c-469e: a busy-road junction costs more at rush hour, less at the
    # weekend and at night.
    factor = time_factor(when, about.urban, junction.control, severe(about))
    untimed = min(cost, MAX_CROSSING_FT)
    cost = min(cost * factor, MAX_CROSSING_FT)
    if factor == UNSIGNALISED_RUSH_FACTOR and kind in GAP_WAIT_KINDS:
        # Rarely an opening at rush hour: never less than ten minutes' riding.
        cost = max(cost, UNSIGNALISED_RUSH_MIN_FT)
    if kind == "left_from" and junction.control is Control.SIGNAL:
        # The box turn is the way out at any hour (468: "box-turn cap at
        # signals"), so rush hour cannot lift a signalised left above it.
        cost = min(cost, BOX_TURN_CAP_FT)
        untimed = min(untimed, BOX_TURN_CAP_FT)
    # Said only where the hour moved the cost by a foot or more.
    band = when if abs(cost - untimed) >= 1.0 else None
    assumed = speed_assumed(about) and junction.control is not Control.SIGNAL
    marked = kind == "crossing" and marked_unsignalised(junction)
    reason = reason_of(kind, about, junction.control, junction.beacon)
    if group:
        if kind in {"left_from", "left_across"} and about.oneway:
            return None
        if kind not in {"crossing", "left_from", "left_across", "left_onto", "slip_lane"}:
            return None
        # A half step on the cautious side (461a): 2.5 orange, 3.5 red.
        severity = RED if about.level >= 3.5 else ORANGE
        return Event(
            junction.m,
            junction.lon,
            junction.lat,
            kind,
            junction.movement,
            junction.control,
            cost,
            severity,
            reason,
            about.tier,
            True,
            junction.approach,
            True,
            road_names=about.names,
            road_display=about.display,
            road_ways=about.ways,
            road_oneway=about.oneway,
            road_lanes=about.lanes,
            assumed_speed=assumed,
            time_factor=factor,
            time_band=band,
            untimed_ft=untimed,
            beacon=junction.beacon,
        )
    cap = MARKED_CROSSING_MAX_SEVERITY if marked else None
    severity = _at_most(severity_of(cost), cap)
    return Event(
        junction.m,
        junction.lon,
        junction.lat,
        kind,
        junction.movement,
        junction.control,
        cost,
        severity,
        reason,
        about.tier,
        severity is not None,
        junction.approach,
        road_names=about.names,
        road_display=about.display,
        max_severity=cap,
        road_ways=about.ways,
        road_oneway=about.oneway,
        road_lanes=about.lanes,
        assumed_speed=assumed,
        time_factor=factor,
        time_band=band,
        untimed_ft=untimed,
        beacon=junction.beacon,
    )


def rated(
    junction: Junction, kind: str, about: Road | None, model_ft: float = 0.0, group: bool = False
) -> Event | None:
    """The event at a junction riders have rated: the rating's cost and colour,
    never capped (a person looked at it), with the model's reason where it has
    one and the riders' rating after it. "Easy" only ever lowers: it costs the
    lesser of its figure and the model's (`model_ft`), and where the model has
    no event there it adds none. On a Mass Ride (`group`) the event carries the
    group reading's flag, so a rated signalized crossing still joins a group."""
    level = junction.rating if junction.rating in RATING_COST_FT else 2
    severity = RATING_SEVERITY[level]
    said = f"Riders rate this junction {RATING_WORDS[level]}"
    quiet = kind == "neighbourhood" or about is None
    cost = RATING_COST_FT[level]
    if level == min(RATING_COST_FT):
        if quiet:
            return None
        cost = min(cost, model_ft)
    if quiet:
        kind = "rated"
        about = max(
            (r for r in (junction.incoming, junction.outgoing) if r.tier is not None),
            key=lambda r: r.level,
            default=junction.outgoing,
        )
        reason = said
    else:
        reason = f"{reason_of(kind, about, junction.control, junction.beacon)}. {said}"
    return Event(
        junction.m,
        junction.lon,
        junction.lat,
        kind,
        junction.movement,
        junction.control,
        cost,
        severity,
        reason,
        about.tier,
        severity is not None,
        junction.approach,
        group,
        road_names=about.names,
        road_display=about.display,
        road_ways=about.ways,
        road_oneway=about.oneway,
        road_lanes=about.lanes,
        rating=level,
        beacon=junction.beacon,
    )


def with_ratings(junctions: Sequence[Junction], ratings: Sequence[Rating]) -> list[Junction]:
    """The junctions with each one's approved rating, where one is within RATING_MATCH_M."""
    if not ratings:
        return list(junctions)
    out = []
    for junction in junctions:
        found = rating_at(junction.lon, junction.lat, ratings)
        out.append(replace(junction, rating=found.level) if found else junction)
    return out


def with_beacons(
    junctions: Sequence[Junction],
    beacons: Sequence[Beacon],
    unsignalled: Sequence[Control] | None = None,
) -> list[Junction]:
    """The junctions with each signalised one at a known flashing beacon priced with no
    signal (`BEACON_MATCH_M`): its control is what the signs say once the map's signal
    is read as nothing (`unsignalled`, one for each junction, from the router's flags;
    `Control.NONE` where not given), so a stop sign mapped on an approach still counts.
    Where the signs say nothing, who flashes red is read from the roads (`beacon_control`).
    A junction with no signal is left as it is."""
    if not beacons:
        return list(junctions)
    out = []
    for index, junction in enumerate(junctions):
        if junction.control is Control.SIGNAL and beacon_at(junction.lon, junction.lat, beacons):
            control = unsignalled[index] if unsignalled is not None else Control.NONE
            if control is Control.NONE:
                control = beacon_control(junction)
            junction = replace(junction, control=control, beacon=True)
        out.append(junction)
    return out


# Roads this many levels apart or more at a beacon: the busier one flashes yellow and
# the quieter one red. Closer than that, every approach flashes red.
BEACON_PRIORITY_LEVELS = 1.0


def beacon_control(junction: Junction) -> Control:
    """Who stops at a flashing beacon whose signs the map does not have, read from the
    roads' stress (the owner, 2026-10-20: "A low stress road crossing a high stress road
    would probably have this issue. A low stress road against a low stress road wouldn't
    have a high penalty to begin with. These are the flashing red vs flashing red."):
    roads a level or more apart are a two-way stop, the quieter road stopping
    (`Control.NONE`, which `crossing_ft` prices by the rider's road against the crossed
    one); roads of about the same stress are an all-way stop."""
    levels = [
        road.level
        for road in (junction.incoming, junction.outgoing, *junction.crossed)
        if road.tier is not None
    ]
    if len(levels) >= 2 and max(levels) - min(levels) < BEACON_PRIORITY_LEVELS:
        return Control.ALL_STOP
    return Control.NONE


# Events this close along the route are one junction as a rider meets it: a
# divided road's two carriageways, a slip lane and its main road, a crossing
# way and the roads at each end of it.
#
# - A divided road crossed carriageway by carriageway - two or more crossings
#   of one-way roads of different ways with a name in common - counts once, the
#   costlier, with the median refuge's credit (items 185 and 196). Crossings of
#   one road that are not that (the same way at two nodes) count once with no
#   credit.
# - Everything else adds, a turn and a crossing of the same road included: the
#   costliest names the junction and each other adds half its cost (two
#   conflicts in one place are worse than one).
# - The merged colour is never more than the worst single event's (item 185: "A
#   merge must never raise the colour of one road's crossing"); the refuge can
#   lower it. Only the cost, which a route is chosen by, adds up.
# - Where riders rated a junction (an approved rating, 232), its rated event
#   stands for that junction's own nodes within RATING_MATCH_M along the
#   route; events beyond are other junctions and add as above.
MERGE_WITHIN_M = 45.0
MERGED_SHARE = 0.5


def _divided(crossings: list[Event]) -> bool:
    """Crossings of a divided road's carriageways: each of a one-way road,
    each of ways of its own."""
    if not all(e.road_oneway and e.road_ways for e in crossings):
        return False
    seen: set[int] = set()
    for event in crossings:
        if seen & event.road_ways:
            return False
        seen |= event.road_ways
    return True


def _one_road(events: list[Event]) -> list[Event]:
    """A road's events at one junction: its crossings as one (a divided road
    crossed once, with the refuge's credit), every other event as it is."""
    # A rated junction's event is the riders' figure, never given a refuge credit.
    crossings = [e for e in events if e.kind == "crossing" and e.rating is None]
    if len(crossings) < 2:
        return events
    rest = [e for e in events if e not in crossings]
    worst = max(crossings, key=lambda e: e.cost_ft)
    if not _divided(crossings):
        return [worst, *rest]
    cost = worst.cost_ft * MEDIAN_REFUGE_FACTOR
    severity = worst.severity
    if not worst.group_severity:
        # The credit only lowers the cost, so this never raises the colour; a
        # trail crossing's cap holds through it.
        severity = _at_most(severity_of(cost), worst.max_severity)
    # The corkers' per-lane rule reads the busier carriageway's lanes (PLAN item 139).
    lanes = [e.road_lanes for e in crossings if e.road_lanes is not None]
    refuge = replace(
        worst,
        cost_ft=cost,
        severity=severity,
        flagged=severity is not None,
        road_divided=True,
        road_lanes=max(lanes) if lanes else None,
        untimed_ft=_untimed(worst) * MEDIAN_REFUGE_FACTOR,
    )
    return [refuge, *rest]


def _rated_stand_in(events: list[Event]) -> list[Event]:
    """A run of nearby events with each rated junction standing for its own
    nodes (232): an unrated event within RATING_MATCH_M along the route of a
    rated one is that junction's other node and drops out, and of several rated
    nodes that close the highest rating counts once. Events farther off are
    other junctions and merge as usual."""
    rated_here = [e for e in events if e.rating is not None]
    if not rated_here:
        return events

    def near(a: Event, b: Event) -> bool:
        return abs(a.m - b.m) <= RATING_MATCH_M

    out = []
    for event in events:
        if event.rating is None:
            if not any(near(event, r) for r in rated_here):
                out.append(event)
            continue
        best = max((r for r in rated_here if near(event, r)), key=lambda r: (r.rating or 0, -r.m))
        if best is event:
            out.append(event)
    return out


def merge_nearby(events: list[Event]) -> list[Event]:
    merged: list[Event] = []
    group: list[Event] = []

    def close() -> None:
        if not group:
            return
        roads: list[list[Event]] = []
        for event in _rated_stand_in(group):
            for same in roads:
                if event.road_names & same[0].road_names:
                    same.append(event)
                    break
            else:
                roads.append([event])
        ones = [one for same in roads for one in _one_road(same)]
        worst = max(ones, key=lambda e: e.cost_ft)
        extra = sum(e.cost_ft for e in ones if e is not worst) * MERGED_SHARE
        cost = min(worst.cost_ft + extra, MAX_CROSSING_FT)
        # The same sum with no ride time: the hour is named only where it moved the
        # merged cost (a capped or rated worst event can sit beside timed ones).
        untimed_extra = sum(_untimed(e) for e in ones if e is not worst) * MERGED_SHARE
        untimed = min(_untimed(worst) + untimed_extra, MAX_CROSSING_FT)
        band = next((e.time_band for e in ones if e.time_band), None)
        severity = _worst(e.severity for e in ones)
        merged.append(
            replace(
                worst,
                cost_ft=cost,
                severity=severity,
                flagged=any(e.flagged for e in ones),
                time_band=band if abs(cost - untimed) >= 1.0 else None,
                untimed_ft=untimed,
            )
        )
        group.clear()

    for event in events:
        if group and event.m - group[-1].m > MERGE_WITHIN_M:
            close()
        group.append(event)
    close()
    return merged


# The nodes of one junction (a divided road's two carriageways, a cycletrack's
# crossing node beside the road junction) often have its control read at one
# of them only: OSM tags the signal on one approach's stop line (review r2:
# Plyers Mill Rd across Connecticut Ave, Columbus Circle). So junctions within
# MERGE_WITHIN_M of each other about a road with a name in common take the
# strongest control of any of them: a signal, then an all-way stop. A stop
# sign is not shared, being one approach's. Two junctions the rider rides the
# shared road between are two (a jog: left onto Main St, then right off it at
# a signal 35 m on; review r3, B2), and so are two the rider reaches by
# different roads, and two that only turn onto and off the road
# (`_one_junction`).
_CONTROL_STRENGTH = {Control.SIGNAL: 2, Control.ALL_STOP: 1}


def _about(junction: Junction) -> frozenset[str]:
    """The names of the roads a junction's conflict is with: the roads it
    crosses, the road it turns or goes onto, and the road it turns off. Not the
    road it rides straight along, so two side streets along one road are not
    one junction."""
    names: set[str] = set()
    for road in junction.crossed:
        names |= road.names
    if not junction.continues:
        names |= junction.outgoing.names
    if junction.movement is not Movement.STRAIGHT:
        names |= junction.incoming.names
    return frozenset(names)


def _one_junction(earlier: Junction, later: Junction, shared: frozenset[str]) -> bool:
    """Whether two nearby junctions about the `shared` road names are nodes of
    one junction. The rider stays on one road from the one to the other (the
    earlier's road out is the later's road in), and a road they are both about
    is one the rider does not ride along between them (review r3, B2: not the
    earlier one's road out) and crosses at one of them: a divided road's two
    carriageways, a turn off one and a crossing of the other, a crossing of one
    and a turn onto the other. A road only turned onto at one and off at the
    other (left off Main St, then left back onto it 30 m on) is two junctions.

    A two-way road a junction crosses that is named like its own road in or
    out is that turn's own opposite lanes (a left off or onto Main St crosses
    Main St), not a road crossed: it does not count (gate 1, B2). A one-way
    carriageway does, so a divided road's crossover still shares."""
    out, into = earlier.outgoing, later.incoming
    if not (out == into or out.names & into.names):
        return False
    crossed = frozenset().union(*_crossings(earlier), *_crossings(later))
    return bool((shared - out.names) & crossed)


def _crossings(junction: Junction) -> list[frozenset[str]]:
    """The names of the roads a junction crosses, less a two-way road named
    like its own road in or out (`_one_junction`)."""
    own = junction.incoming.names | junction.outgoing.names
    return [road.names for road in junction.crossed if road.oneway or not road.names & own]


def share_controls(junctions: list[Junction]) -> list[Junction]:
    """Each junction with the strongest control among the junctions within
    MERGE_WITHIN_M of it along the route about a road of the same name, where
    the two are one junction (`_one_junction`)."""
    order = sorted(range(len(junctions)), key=lambda i: junctions[i].m)
    abouts = {i: _about(junctions[i]) for i in order}
    shared = list(junctions)
    for place, i in enumerate(order):
        junction = junctions[i]
        if junction.beacon:
            # Its signal is a beacon's: a neighbouring node's signal flag is the same one.
            continue
        best = junction.control
        near = [k for step in (-1, 1) for k in _within(order, place, step, junctions, junction.m)]
        for k in near:
            other = junctions[k]
            shared_names = abouts[i] & abouts[k]
            if not shared_names or _CONTROL_STRENGTH.get(other.control, 0) <= _CONTROL_STRENGTH.get(
                best, 0
            ):
                continue
            earlier, later = (other, junction) if other.m <= junction.m else (junction, other)
            if _one_junction(earlier, later, shared_names):
                best = other.control
        if best is not junction.control:
            shared[i] = replace(junction, control=best)
    return shared


def _within(order: list[int], place: int, step: int, junctions: list[Junction], m: float):
    """The junctions before (step -1) or after (step 1) `order[place]` within
    MERGE_WITHIN_M of `m`, in route order."""
    k = place + step
    while 0 <= k < len(order) and abs(junctions[order[k]].m - m) <= MERGE_WITHIN_M:
        yield order[k]
        k += step


# --- Mass Ride: signalized crossings read as groups (items 233 and 234) --------
#
# The owner, 2026-10-03 (item 233, amending 231's "Leave as is."): "Actually, I
# like merging the runs, that sounds good." And (item 234): "I'd say we'd want
# some level of clumpings, especially in DC, given the diagional streets. I'd
# say something like a quarter mile or so of clumping." Every LTS 3/4 crossing
# is still flagged and still drawn (item 231); what changes is how the list and
# the description say it: consecutive signalized crossings, each within a
# quarter mile of the one before, are one entry, whatever street they are on.
#
# - Only a signalized crossing joins: a flagged event with a signal whose kind
#   is a crossing of a busy road (`GROUPED_KINDS`). A turn at a signal is a
#   decision of its own and is said where it is.
# - Any other flagged event - an unsignalized crossing, a very-high-stress one
#   with no signal, a turn - stands alone and ends the run.
# - A run of one is not a group.
# - The group's colour is its worst member's (`CrossingGroup.severity`), the
#   words and shapes the markers already use.
GROUP_WITHIN_M = 402.0  # a quarter mile (0.25 mi = 402.3 m), "or so"
GROUPED_KINDS = frozenset({"crossing", "left_across"})
# At or above this tier a crossed road counts as "LTS 4" in a group's wording
# (an Avoid road is worse still).
GROUP_LTS4_TIER = 4


def groupable(event: Event) -> bool:
    """A flagged, signalized Mass Ride crossing of a busy road."""
    return (
        event.group_severity
        and event.flagged
        and event.control is Control.SIGNAL
        and event.kind in GROUPED_KINDS
    )


def number_groups(events: list[Event], stops: Sequence[float] = ()) -> list[Event]:
    """The events, in route order, with each run of two or more signalized
    crossings (each within GROUP_WITHIN_M of the one before) numbered from 1 in
    `Event.group`. Only flagged events count: an event the planner never draws
    neither joins a run nor ends one.

    `stops` are where each leg ends (metres along the route, in the events'
    measure): a run never spans one (OWNER-DECISIONS 247: "Split at stops"), so
    a crossing at or past a stop starts a new run. Any group an event had
    before is replaced, so the groups can be numbered again once the stops are
    known (`core.routing`)."""
    numbered = [e if e.group is None else replace(e, group=None) for e in events]
    stops = sorted(stops)
    run: list[int] = []
    number = 0

    def across_a_stop(before: float, at: float) -> bool:
        """Whether a stop lies after `before` and at or before `at`."""
        i = bisect.bisect_right(stops, before)
        return i < len(stops) and stops[i] <= at

    def close() -> None:
        nonlocal number
        if len(run) >= 2:
            number += 1
            for i in run:
                numbered[i] = replace(numbered[i], group=number)
        run.clear()

    for i, event in enumerate(events):
        if not event.flagged:
            continue
        if not groupable(event):
            close()
            continue
        if run and (
            event.m - events[run[-1]].m > GROUP_WITHIN_M
            or across_a_stop(events[run[-1]].m, event.m)
        ):
            close()
        run.append(i)
    close()
    return numbered


@dataclass(frozen=True)
class CrossingGroup:
    """A group of signalized crossings, as the list and the description say it."""

    number: int
    members: tuple[Event, ...]

    @property
    def from_m(self) -> float:
        return self.members[0].m

    @property
    def to_m(self) -> float:
        return self.members[-1].m

    @property
    def count(self) -> int:
        return len(self.members)

    @property
    def lts4(self) -> int:
        """How many of the crossed roads are LTS 4 or worse."""
        return sum(1 for e in self.members if (e.crossed_tier or 0) >= GROUP_LTS4_TIER)

    @property
    def severity(self) -> str:
        """The worst member's: never milder than any crossing in it."""
        return _worst(e.severity for e in self.members) or ORANGE


def crossing_groups(events: list[Event]) -> list[CrossingGroup]:
    """The groups `number_groups` made, in route order."""
    found: dict[int, list[Event]] = {}
    for event in sorted(events, key=lambda e: e.m):
        if event.group is not None:
            found.setdefault(event.group, []).append(event)
    return [CrossingGroup(n, tuple(found[n])) for n in sorted(found)]


def assess_route(
    junctions: list[Junction],
    group: bool = False,
    stops: Sequence[float] = (),
    when: str | None = None,
) -> list[Event]:
    """Every junction's event, in route order (a cost the objective sums; the
    flagged ones are what the planner draws). The nodes of one junction share
    its strongest control first (`share_controls`). On a Mass Ride (`group`)
    the signalized crossings that run together are numbered (`number_groups`),
    never across a stop (`stops`, where each leg ends). `when` is the ride time
    (`time_factor`, 468a)."""
    events = (assess(junction, group, when) for junction in share_controls(junctions))
    merged = merge_nearby(sorted((e for e in events if e is not None), key=lambda e: e.m))
    return number_groups(merged, stops) if group else merged


def penalty_m(events: list[Event]) -> float:
    """The events' total cost as metres of quiet-street riding."""
    return sum(event.cost_ft for event in events) / FEET_PER_METRE


# --- Major junctions, for the Mass Ride route chart ----------------------------

# OWNER-DECISIONS 396, which replaces 333's lane-count rule: "Similar rules to other
# riding. Go by stress ratings of the roads." A junction is major on the Mass Ride chart
# when the road it crosses or joins is rated LTS 3 or higher (`BUSY_TIER`), whatever the
# control (a signal, a stop, or none), or when the junction itself carries a stress
# rating (an event the planner flags). There is no lane counting and no "any stop sign"
# rule. Busy roads the group reading turns into no event are marked all the same: a
# right turn onto an arterial, or riding along a busy road past a busy cross street.
# Corkers are needed at the major junctions (142, by the crossed or joined road's tier:
# LTS 3, 4 or Avoid; 400: a left or right turn onto such a road needs them as a crossing
# does).
CORKER_TIER = BUSY_TIER

# What made a junction major: a flagged event, a busy road crossed, or one joined.
MAJOR_FLAGGED = "flagged"
MAJOR_CROSSING = "crossing"
MAJOR_JOINING = "joining"


@dataclass(frozen=True)
class Major:
    """A major junction of a route: where, which street, how it is controlled."""

    m: float
    lon: float
    lat: float
    # The crossed or joined street's names, as `Event.road_names` and `.road_display`.
    names: frozenset[str]
    display: tuple[str, ...]
    # The planner's own marker where the junction is flagged: orange or red; None where
    # it is major only for the busy road it crosses or joins.
    severity: str | None
    control: Control
    # The street's lanes in all (both directions), where known: said, not counted.
    lanes: int | None
    # The tier of the road that makes it major: the road crossed, or for a joining
    # (`kind`) the road joined. The name is the API's (`crossed_tier`), kept for its
    # callers; corkers follow it either way (142, 400: a turn onto an LTS 3+ road needs
    # them as a crossing does).
    crossed_tier: int | None
    kind: str = MAJOR_FLAGGED
    # Whether that road is one-way there, where known: one approach to hold, so one
    # corker rather than two (PLAN item 139).
    oneway: bool | None = None
    # A divided road (its two one-way carriageways counted as one major): two
    # approaches to hold, so two corkers whatever `oneway` says (re-check, BLOCKING 1).
    divided: bool = False
    # Through lanes on each approach to hold, where known (`Road.lanes`: per direction;
    # a divided road's busier carriageway): the chart's per-lane rule (PLAN item 139:
    # one corker an approach lane where no signal holds the cross traffic).
    approach_lanes: int | None = None

    @property
    def road_names(self) -> frozenset[str]:
        return self.names

    @property
    def road_display(self) -> tuple[str, ...]:
        return self.display

    @property
    def corkers_needed(self) -> bool:
        return (self.crossed_tier or 0) >= CORKER_TIER


class RouteEvents(list):
    """The junction events of a Mass Ride route, with its major junctions beside them
    (`majors`, in route order). `complete` False: the majors are the flagged junctions
    only, because finding the busy-road ones failed (`core.junctions.with_majors`), so
    the chart says the list may be incomplete (correctness re-review R3)."""

    majors: list[Major]
    complete: bool

    def __init__(self, events=(), majors=(), complete: bool = True):
        super().__init__(events)
        self.majors = list(majors)
        self.complete = complete


def majors_of_events(events: Sequence[Event]) -> list[Major]:
    """The major junctions that are flagged ones: each junction with a stress rating."""
    return [
        Major(
            e.m,
            e.lon,
            e.lat,
            e.road_names,
            e.road_display,
            e.severity,
            e.control,
            None,
            e.crossed_tier,
            MAJOR_FLAGGED,
            e.road_oneway,
            e.road_divided,
            e.road_lanes,
        )
        for e in events
        if e.flagged
    ]


def busy_roads_at(junction: Junction) -> list[tuple[Road, str]]:
    """The roads of LTS 3 or higher a junction crosses or joins, busiest first, each
    with how (`MAJOR_CROSSING`, `MAJOR_JOINING`). Joined is the road turned or run onto
    from another one (not the rider's own road going on, and not straight on from one
    busy road into the next, which `cost_of` does not count as joining either)."""
    found = [(road, MAJOR_CROSSING) for road in junction.crossed if road.busy]
    out = junction.outgoing
    if (
        out.busy
        and not junction.continues
        and (not junction.incoming.busy or junction.movement is not Movement.STRAIGHT)
    ):
        found.append((out, MAJOR_JOINING))
    return sorted(found, key=lambda pair: -(pair[0].tier or 0))


def _counted_by(
    majors: Sequence[Major], at: Sequence[float], junction: Junction, road: Road
) -> int | None:
    """Whether a junction's busy road is one already counted: the same node, or the
    same street within MERGE_WITHIN_M (its other carriageway, a slip lane), or an
    unnamed road there. An unnamed major (a path crossing, say) does not hide a named
    busy road beside it (correctness re-review NIT). `majors` is sorted by `m` and `at`
    is their `m`s, so only the ones within MERGE_WITHIN_M are looked at (operations
    re-review C)."""
    lo = bisect.bisect_left(at, junction.m - MERGE_WITHIN_M)
    hi = bisect.bisect_right(at, junction.m + MERGE_WITHIN_M)
    for index in range(lo, hi):
        major = majors[index]
        if major.m == junction.m or major.names & road.names or not road.names:
            return index
    return None


def _counted(majors: Sequence[Major], at: Sequence[float], junction: Junction, road: Road) -> bool:
    """Whether a junction's busy road is one already counted (`_counted_by`)."""
    return _counted_by(majors, at, junction, road) is not None


def _other_carriageway(major: Major, junction: Junction, road: Road) -> bool:
    """Whether a busy road hidden by a counted major is that road's other carriageway:
    the same street, one-way both, at another node within MERGE_WITHIN_M."""
    return (
        major.m != junction.m
        and bool(major.names & road.names)
        and major.oneway is True
        and road.oneway is True
    )


def major_crossings(junctions: Sequence[Junction], events: Sequence[Event]) -> list[Major]:
    """A route's major junctions (OWNER-DECISIONS 396), in route order: the flagged
    events, and every other junction that crosses or joins a road of LTS 3 or higher,
    whatever its control. One junction gives one major, for its busiest road."""
    majors = sorted(majors_of_events(events), key=lambda major: major.m)
    at = [major.m for major in majors]
    for junction in sorted(share_controls(list(junctions)), key=lambda j: j.m):
        for road, kind in busy_roads_at(junction):
            hidden = _counted_by(majors, at, junction, road)
            if hidden is not None:
                # A divided road's far carriageway: the major it is counted with has two
                # approaches to hold (corkers), though each carriageway is one-way.
                if _other_carriageway(majors[hidden], junction, road):
                    near = majors[hidden]
                    known = [n for n in (near.approach_lanes, road.lanes) if n is not None]
                    majors[hidden] = replace(
                        near, divided=True, approach_lanes=max(known) if known else None
                    )
                break
            place = bisect.bisect_right(at, junction.m)
            at.insert(place, junction.m)
            majors.insert(
                place,
                Major(
                    junction.m,
                    junction.lon,
                    junction.lat,
                    road.names,
                    road.display,
                    None,
                    junction.control,
                    _lanes_total(road),
                    road.tier,
                    kind,
                    road.oneway,
                    False,
                    road.lanes,
                ),
            )
            break
    return majors
