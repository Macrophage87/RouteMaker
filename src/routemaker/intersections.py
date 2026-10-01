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

Every number below is a PROPOSAL for the owner, taken from
reports/LTS-literature-review-2.md, "Crossing penalties by control type and
right of way" and "Left turns, multi-lane merges capped by box turns, and slip
lanes". They are judgement within the cited ranges (Broach et al.'s per-mile
values, Eugene's 818 ft per left, Copenhagen's 154 ft left against 62 ft
right, Oregon's LTS tables) and are named so the owner's answers are one-line
changes. Nothing here is a legal claim; the DC roll-through rule (item 171) is
the owner's account.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
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

# A mapped crossing way (Valhalla's `pedestrian_crossing`) is a crosswalk, a
# beacon or a signal, and OSM's `crossing=traffic_signals` and its kin do not
# reach the router's signal flag (`highway=traffic_signals` alone does), so a
# signalised trail crossing reads as "no signal". Counted at this fraction of the
# stopped-side cost until the transform derives the signal (docs/OPERATIONS.md,
# "Intersection costs"). A PROPOSAL; it never lowers a junction the router says
# has a signal, which is already priced as one.
MARKED_CROSSING_FACTOR = 0.5

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
# 1-way", item 133). Lower at a signal, where the left has its own phase.
LEFT_ACROSS_ONCOMING_FT = {3: 600.0, 4: 1500.0, 5: 1500.0}
SIGNALISED_LEFT_FACTOR = 0.4
RIGHT_FROM_BUSY_FT = 15.0

# "having to cross several lanes to get into the left turn can add stress too,
# though box turns are an option" (item 167): feet per lane merged across, per
# direction, capped at about a two-stage box turn (two crossings and one extra
# signal wait: 200-500 ft at a signalised junction).
MERGE_FT_PER_LANE = 250.0
BOX_TURN_CAP_FT = 500.0
# Where the lane count is unknown, a road of this tier is read at this many
# lanes a direction for the merge.
ASSUMED_LANES = {3: 1, 4: 2, 5: 2}

# --- Slip lanes (item 169) ---------------------------------------------------
#
# "Sliplanes should get a penalty too": a free-flowing channelised right-turn
# lane crossed as at least an unsignalised LTS 3 crossing, about 800 ft, unless
# a raised crossing is tagged (not read). Halved at a signal.
SLIP_LANE_FT = 800.0
SIGNALISED_SLIP_FACTOR = 0.5

# --- Severity (item 172) ----------------------------------------------------
#
# A stopped-side crossing of an LTS 3 road (800-1,600 ft) is orange; of an LTS 4
# road (2,500-3,500 ft) red; a left onto or across an LTS 3 road is orange, red
# when the road is fast. A signalised crossing (150-300 ft) is neither.
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
    # A slip lane (Valhalla's turn channel) joins here or is the route's own way.
    slip_lane: bool = False
    # The route crosses by a mapped crossing way (a trail crossing a road).
    marked_crossing: bool = False
    # A point on the edge the route arrives by, which a re-plan excludes to
    # make the router approach another way (`core.refine`).
    approach: tuple[float, float] | None = None


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
    one-way) and over its other lanes to the left-turn position."""
    oncoming = 0.0 if road.oneway else LEFT_ACROSS_ONCOMING_FT[_tier(road)]
    if oncoming:
        oncoming *= scale(road, stopped_side=False)
        if control is Control.SIGNAL:
            oncoming *= SIGNALISED_LEFT_FACTOR
    return min(oncoming + merge_ft(road), MAX_CROSSING_FT)


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
    if j.outgoing.busy and not j.incoming.busy:
        # Entering a busy road from a quieter one: the stopped side's crossing
        # cost, by the movement.
        factor = MOVEMENT_FACTOR_ONTO[j.movement.value]
        base = crossing_ft(j.outgoing, j.control, j.incoming.tier)
        take(base * factor, f"{j.movement.value}_onto", j.outgoing)
    for road in (r for r in j.crossed if r.busy):
        if j.movement is Movement.STRAIGHT:
            value = crossing_ft(road, j.control, j.incoming.tier)
            if j.marked_crossing and j.control in {Control.NONE, Control.STOP}:
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
            take(value, "left_across", road)
    if j.slip_lane:
        # About the busiest road the channel leaves or joins.
        roads = [r for r in (j.incoming, j.outgoing, *j.crossed) if r.busy]
        busiest = max(roads, key=lambda r: r.tier or 0) if roads else None
        take(slip_ft(j.control) if busiest else 0.0, "slip_lane", busiest)
    if about is None and not j.incoming.busy and not j.outgoing.busy:
        # Quiet street meets quiet street: a stop sign here is the owner's
        # "rolls through when safe", priced near zero.
        cost = NEIGHBOURHOOD_STOP_FT if j.control in {Control.STOP, Control.ALL_STOP} else 0.0
    return cost, kind, about


def severity_of(cost_ft: float) -> str | None:
    if cost_ft >= RED_MIN_FT:
        return RED
    if cost_ft >= ORANGE_MIN_FT:
        return ORANGE
    return None


def _lanes_total(road: Road) -> int | None:
    if road.lanes is None:
        return None
    return road.lanes if road.oneway else road.lanes * 2


def describe_road(road: Road | None) -> str:
    """ "4-lane 35 mph (56 km/h) road", or what is known of one."""
    if road is None:
        return "road"
    parts = []
    lanes = _lanes_total(road)
    if lanes:
        parts.append(f"{lanes}-lane")
    if road.speed_mph:
        kmh = round(road.speed_mph * KMH_PER_MPH)
        parts.append(f"{round(road.speed_mph)} mph ({kmh} km/h)")
    parts.append("road")
    text = " ".join(parts)
    if not lanes and not road.speed_mph and road.tier:
        text += f" (LTS {road.tier})"
    return text


CONTROL_WORDS = {
    Control.SIGNAL: "traffic signal",
    Control.STOP: "stop sign on your side",
    Control.CROSS_STOP: "cross traffic stops",
    Control.ALL_STOP: "all-way stop",
    Control.NONE: "no signal",
}

KIND_WORDS = {
    "crossing": "Crossing a",
    "left_onto": "Left turn onto a",
    "right_onto": "Right turn onto a",
    "straight_onto": "Joining a",
    "left_across": "Left turn across a",
    "left_from": "Left turn across a",
    "right_from": "Right turn off a",
    "along": "Side streets along a",
    "slip_lane": "Slip lane beside a",
}


def reason_of(kind: str, road: Road | None, control: Control) -> str:
    """The sentence a click on the marker shows, in US units first (the
    owner's example: "Left turn across 4-lane 35 mph road, no signal")."""
    return (
        f"{KIND_WORDS.get(kind, 'Junction with a')} {describe_road(road)}, {CONTROL_WORDS[control]}"
    )


def assess(junction: Junction, group: bool = False) -> Event | None:
    """The event at one junction, or None where there is nothing to say.

    `group` is the Mass Ride reading (items 133 and 138: "put an orange warning
    icon across any LTS3 intersection and a red one across an LTS4"): the colour
    is the busy road's own tier, orange for LTS 3 and red for LTS 4 or Avoid, and
    a left across a one-way road gets none. The cost is still the model's."""
    cost, kind, about = cost_of(junction)
    if kind == "neighbourhood" or about is None:
        return None
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
            reason_of(kind, about, junction.control),
            about.tier,
            True,
            junction.approach,
            True,
        )
    severity = severity_of(cost)
    return Event(
        junction.m,
        junction.lon,
        junction.lat,
        kind,
        junction.movement,
        junction.control,
        cost,
        severity,
        reason_of(kind, about, junction.control),
        about.tier,
        severity is not None,
        junction.approach,
    )


# Events this close along the route are one junction as a rider meets it: a
# divided road's two carriageways, a slip lane and its main road, a crossing
# way and the roads at each end of it. The costliest names it; the rest add
# half (a median is a refuge, which Mineta and Oregon both read as a level
# lower), so a divided road costs less than two separate ones.
MERGE_WITHIN_M = 45.0
MERGED_SHARE = 0.5


def merge_nearby(events: list[Event]) -> list[Event]:
    merged: list[Event] = []
    group: list[Event] = []

    def close() -> None:
        if not group:
            return
        worst = max(group, key=lambda e: e.cost_ft)
        extra = sum(e.cost_ft for e in group if e is not worst) * MERGED_SHARE
        cost = min(worst.cost_ft + extra, MAX_CROSSING_FT)
        severity = worst.severity
        if worst.flagged and not worst.group_severity:
            severity = severity_of(cost) or worst.severity
        merged.append(replace(worst, cost_ft=cost, severity=severity))
        group.clear()

    for event in events:
        if group and event.m - group[-1].m > MERGE_WITHIN_M:
            close()
        group.append(event)
    close()
    return merged


def assess_route(junctions: list[Junction], group: bool = False) -> list[Event]:
    """Every junction's event, in route order (a cost the objective sums; the
    flagged ones are what the planner draws)."""
    events = (assess(junction, group) for junction in junctions)
    return merge_nearby(sorted((e for e in events if e is not None), key=lambda e: e.m))


def penalty_m(events: list[Event]) -> float:
    """The events' total cost as metres of quiet-street riding."""
    return sum(event.cost_ft for event in events) / FEET_PER_METRE
