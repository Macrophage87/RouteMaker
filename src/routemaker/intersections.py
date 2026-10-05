"""The intersection cost model: what a junction on a route costs a rider.

OWNER-DECISIONS items 165 to 169, 171 and 172 (2026-10-01), quoted where each
rule is written. The model has two outputs from one function: a cost in feet of
equivalent quiet-street riding (`Event.cost_ft`), which the router's candidate
choice weighs (`core.routing`), and a severity - orange "higher" or red "very
high" - which the planner draws on the route (item 172, "put markers on
intersections in a route, such as an orange marker for higher stress
intersections and a red one for very high stress intersections").

Why this is not in the graph. Valhalla 3.5.1's bicycle costing has no hook that
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

Every number below is a PROPOSAL for the owner, taken from "Bicycle stress
literature in depth" (reports/LTS-literature-review-2.md), "Crossing penalties
by control type and right of way" and "Left turns, multi-lane merges capped by
box turns, and slip lanes". They are judgement within the cited ranges (Broach et al.'s per-mile
values, Eugene's 818 ft per left, Copenhagen's 154 ft left against 62 ft
right, Oregon's LTS tables) and are named so the owner's answers are one-line
changes. Nothing here is a legal claim; the DC roll-through rule (item 171) is
the owner's account.
"""

from __future__ import annotations

import bisect
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum

FEET_PER_METRE = 3.28084
KMH_PER_MPH = 1.609344

# --- Which roads count -----------------------------------------------------

# "an at-grade crossing of an LTS 3+ road" (item 165). Tiers below this are
# neighbourhood streets: "neighbourhood stop signs (LTS 1-2 meeting LTS 1-2) cost
# near zero" (item 171).
BUSY_TIER = 3

# --- Base crossing cost, from the STOPPED side against free-flowing traffic ---
#
# Feet of equivalent quiet-street riding by the crossed road's tier. Literature
# review: LTS 3 800-1,600 ft (Eugene 818 ft; Broach 10-20k ADT 6-10% a mile),
# LTS 4 2,500-3,500 ft (Broach 20k+ ADT, 1,700-3,260 ft). The midpoints.
STOPPED_CROSSING_FT = {3: 1200.0, 4: 3000.0, 5: 3000.0}

# "Much lower penalty for traffic signals" (item 165): 100-200 ft for a signal
# with detection, wider roads on a short phase more. Mostly delay.
SIGNALISED_CROSSING_FT = {3: 150.0, 4: 300.0, 5: 300.0}

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
# - is a crosswalk, a beacon or a signal, and OSM's `crossing=traffic_signals`
# and its kin do not reach the router's signal flag (`highway=traffic_signals`
# alone does, on the road junction's own node or its stop lines a few metres
# away, which `core.junctions` reads up to 30 m along the crossed road), so a
# signalized trail crossing away from a signalized road junction reads as
# having no signal. Counted at this fraction
# of the stopped-side cost until the transform derives the signal
# (docs/OPERATIONS.md, "Intersection costs"). A PROPOSAL; it never lowers a
# junction the router says has a signal, which is already priced as one.
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
MAX_CROSSING_FT = 4500.0

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
LEFT_ACROSS_ONCOMING_FT = {3: 600.0, 4: 1500.0, 5: 1500.0}
SIGNALISED_LEFT_FACTOR = 0.4
RIGHT_FROM_BUSY_FT = 15.0

# "having to cross several lanes to get into the left turn can add stress too,
# though box turns are an option" (item 167): feet per lane merged across, per
# direction, capped at about a two-stage box turn (two crossings and one extra
# signal wait: 200-500 ft at a signalized junction). At a signal the whole left
# is capped there too, oncoming lanes and merge together (item 186, "Cap at box
# turn": "At signals a left never costs more than the two-stage box-turn
# alternative (about 500 ft equivalent)").
MERGE_FT_PER_LANE = 250.0
BOX_TURN_CAP_FT = 500.0
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
SLIP_LANE_FT = 800.0
SIGNALISED_SLIP_FACTOR = 0.5

# --- Severity (item 172) ----------------------------------------------------
#
# A stopped-side crossing of an LTS 3 road (800-1,600 ft) is orange; of an LTS 4
# road (2,500-3,500 ft) red; a left onto or across an LTS 3 road is orange, red
# when the road is fast. A signalized crossing (150-300 ft) is neither.
ORANGE_MIN_FT = 600.0
RED_MIN_FT = 2000.0
ORANGE = "orange"
RED = "red"

# How far from straight on is still "straight", and the angle past which it is
# a reversal rather than a turn.
STRAIGHT_MAX_DEG = 35.0


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

    @property
    def busy(self) -> bool:
        return self.tier is not None and self.tier >= BUSY_TIER


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
    # A Mass Ride's signalized crossings that run within GROUP_WITHIN_M of one
    # another are one group, numbered from 1 in route order (`number_groups`;
    # items 233 and 234). None: not in a group, and always None off a Mass Ride.
    group: int | None = None


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


def scale(road: Road, stopped_side: bool) -> float:
    """The crossed road's speed, width, volume and rurality, as a multiplier on
    the tier's base cost. Unknown inputs are 1.0, not guessed."""
    factor = 1.0
    if road.speed_mph is not None:
        factor *= _band(road.speed_mph, SPEED_FACTORS, SPEED_FACTOR_FASTER)
        if stopped_side and road.speed_mph >= RURAL_SPEED_MPH:
            factor *= RURAL_FACTOR
    if road.lanes is not None:
        factor *= LANE_FACTORS.get(road.lanes, LANE_FACTOR_WIDER)
    if road.aadt is not None:
        factor *= _band(float(road.aadt), VOLUME_FACTORS, VOLUME_FACTOR_BUSIER)
    return factor


def _tier(road: Road) -> int:
    """The tier a busy road's table is read at (4 stands for 5 as well)."""
    return min(max(road.tier or BUSY_TIER, BUSY_TIER), 5)


def crossing_ft(road: Road, control: Control, rider_tier: int | None) -> float:
    """Straight across `road` (busy) from the rider's road.

    The big cost is the STOPPED side against free-flowing traffic; at a signal
    it is much lower; on the free-flowing road, through a junction where the
    cross traffic stops, it is small (items 165 and 169)."""
    tier = _tier(road)
    if control is Control.SIGNAL:
        return SIGNALISED_CROSSING_FT[tier]
    if control is Control.ALL_STOP:
        return ALL_WAY_STOP_FT
    # The rider's own road has priority: it is the busier road, or the cross
    # traffic is the one facing the sign.
    if control is Control.CROSS_STOP:
        return PRIORITY_SIDE_FT
    if control is Control.NONE and rider_tier is not None and rider_tier > (road.tier or 0):
        return PRIORITY_SIDE_FT
    return min(STOPPED_CROSSING_FT[tier] * scale(road, stopped_side=True), MAX_CROSSING_FT)


def merge_ft(road: Road) -> float:
    """Lanes the rider must cross to reach the left-turn position, capped at a
    box turn (item 167). `road.lanes` is lanes per direction."""
    lanes = road.lanes if road.lanes is not None else ASSUMED_LANES.get(_tier(road), 1)
    return min(MERGE_FT_PER_LANE * max(lanes - 1, 0), BOX_TURN_CAP_FT)


def left_from_ft(road: Road, control: Control) -> float:
    """A left turn off a busy road: across its oncoming lanes (none on a
    one-way) and over its other lanes to the left-turn position. At a signal
    never more than the box turn the rider can make instead (item 186)."""
    oncoming = 0.0 if road.oneway else LEFT_ACROSS_ONCOMING_FT[_tier(road)]
    if oncoming:
        oncoming *= scale(road, stopped_side=False)
        if control is Control.SIGNAL:
            oncoming *= SIGNALISED_LEFT_FACTOR
    total = oncoming + merge_ft(road)
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
        and ((j.outgoing.tier or 0) > (j.incoming.tier or 0) or j.control is Control.STOP)
    )
    if j.outgoing.busy and not j.continues and (not j.incoming.busy or turning_from_busy_onto):
        # Entering a busy road from a quieter one, or from the stopped side:
        # the stopped side's crossing cost, by the movement.
        factor = MOVEMENT_FACTOR_ONTO[j.movement.value]
        base = crossing_ft(j.outgoing, j.control, j.incoming.tier)
        take(min(base * factor, MAX_CROSSING_FT), f"{j.movement.value}_onto", j.outgoing)
    for road in (r for r in j.crossed if r.busy):
        if j.movement is Movement.STRAIGHT:
            value = crossing_ft(road, j.control, j.incoming.tier)
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
            value = crossing_ft(road, j.control, j.incoming.tier) * MOVEMENT_FACTOR_ONTO["left"]
            take(min(value, MAX_CROSSING_FT), "left_across", road)
    if j.slip_lane:
        # About the busiest road the channel leaves or joins.
        roads = [r for r in (j.incoming, j.outgoing, *j.crossed, *j.links) if r.busy]
        busiest = max(roads, key=lambda r: r.tier or 0) if roads else None
        take(slip_ft(j.control) if busiest else 0.0, "slip_lane", busiest)
    if about is None and not j.incoming.busy and not j.outgoing.busy:
        # Quiet street meets quiet street: a stop sign here is the owner's
        # "rolls through when safe", priced near zero.
        cost = NEIGHBOURHOOD_STOP_FT if j.control in {Control.STOP, Control.ALL_STOP} else 0.0
    return cost, kind, about


def marked_unsignalised(junction: Junction) -> bool:
    """A trail crossing with no signal mapped there (no flag at all, or a stop
    or yield on the rider's side): the route crosses by a mapped crossing way,
    or arrives or leaves on a path, trail, cycletrack or sidewalk (item 185:
    "Trail crossings whose signal is not mapped cap at orange")."""
    trail = junction.marked_crossing or junction.path_crossing
    return trail and junction.control in {Control.NONE, Control.STOP}


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


def reason_of(kind: str, road: Road | None, control: Control) -> str:
    """The sentence a click on the marker shows, in US units first (the
    owner's example: "Left turn across 4-lane 35 mph road, no signal")."""
    noun = describe_road(road)
    words = CONTROL_WORDS[control]
    return f"{KIND_WORDS.get(kind, 'Junction with')} {_article(noun)} {noun}, {words}"


def assess(junction: Junction, group: bool = False) -> Event | None:
    """The event at one junction, or None where there is nothing to say.

    `group` is the Mass Ride reading (items 133 and 138: "put an orange warning
    icon across any LTS3 intersection and a red one across an LTS4"): the colour
    is the busy road's own tier, orange for LTS 3 and red for LTS 4 or Avoid, and
    a left across a one-way road gets none. The cost is still the model's."""
    cost, kind, about = cost_of(junction)
    if kind == "neighbourhood" or about is None:
        return None
    marked = kind == "crossing" and marked_unsignalised(junction)
    reason = reason_of(kind, about, junction.control)
    if group:
        if kind in {"left_from", "left_across"} and about.oneway:
            return None
        if kind not in {"crossing", "left_from", "left_across", "left_onto", "slip_lane"}:
            return None
        severity = RED if (about.tier or 0) >= 4 else ORANGE
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
    )


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
    crossings = [e for e in events if e.kind == "crossing"]
    if len(crossings) < 2:
        return events
    rest = [e for e in events if e.kind != "crossing"]
    worst = max(crossings, key=lambda e: e.cost_ft)
    if not _divided(crossings):
        return [worst, *rest]
    cost = worst.cost_ft * MEDIAN_REFUGE_FACTOR
    severity = worst.severity
    if not worst.group_severity:
        # The credit only lowers the cost, so this never raises the colour; a
        # trail crossing's cap holds through it.
        severity = _at_most(severity_of(cost), worst.max_severity)
    refuge = replace(worst, cost_ft=cost, severity=severity, flagged=severity is not None)
    return [refuge, *rest]


def merge_nearby(events: list[Event]) -> list[Event]:
    merged: list[Event] = []
    group: list[Event] = []

    def close() -> None:
        if not group:
            return
        roads: list[list[Event]] = []
        for event in group:
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
        severity = _worst(e.severity for e in ones)
        merged.append(
            replace(worst, cost_ft=cost, severity=severity, flagged=any(e.flagged for e in ones))
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
    junctions: list[Junction], group: bool = False, stops: Sequence[float] = ()
) -> list[Event]:
    """Every junction's event, in route order (a cost the objective sums; the
    flagged ones are what the planner draws). The nodes of one junction share
    its strongest control first (`share_controls`). On a Mass Ride (`group`)
    the signalized crossings that run together are numbered (`number_groups`),
    never across a stop (`stops`, where each leg ends)."""
    events = (assess(junction, group) for junction in share_controls(junctions))
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


def _counted(majors: Sequence[Major], at: Sequence[float], junction: Junction, road: Road) -> bool:
    """Whether a junction's busy road is one already counted: the same node, or the
    same street within MERGE_WITHIN_M (its other carriageway, a slip lane), or an
    unnamed road there. An unnamed major (a path crossing, say) does not hide a named
    busy road beside it (correctness re-review NIT). `majors` is sorted by `m` and `at`
    is their `m`s, so only the ones within MERGE_WITHIN_M are looked at (operations
    re-review C)."""
    lo = bisect.bisect_left(at, junction.m - MERGE_WITHIN_M)
    hi = bisect.bisect_right(at, junction.m + MERGE_WITHIN_M)
    for major in majors[lo:hi]:
        if major.m == junction.m or major.names & road.names or not road.names:
            return True
    return False


def major_crossings(junctions: Sequence[Junction], events: Sequence[Event]) -> list[Major]:
    """A route's major junctions (OWNER-DECISIONS 396), in route order: the flagged
    events, and every other junction that crosses or joins a road of LTS 3 or higher,
    whatever its control. One junction gives one major, for its busiest road."""
    majors = sorted(majors_of_events(events), key=lambda major: major.m)
    at = [major.m for major in majors]
    for junction in sorted(share_controls(list(junctions)), key=lambda j: j.m):
        for road, kind in busy_roads_at(junction):
            if _counted(majors, at, junction, road):
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
                ),
            )
            break
    return majors
