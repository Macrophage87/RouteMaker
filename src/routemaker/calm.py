"""The rolling stress score along a route, in calm miles per mile (OWNER-DECISIONS 460.12,
461, 461a-e, 469b; docs/DEVELOPMENT.md "The rolling stress chart").

460.12: "A chart of rolling traffic stress makes more sense than a strip. That way, spikes
show up." 461c: build it from the costs the routing already charges, "a sort of hidden
number". 461d: the metric is calm miles per actual mile, junctions included. 461e: a
window of about a mile, centred on each point, cut at the route's ends, each junction
counted once in every window that holds it.

A calm mile is a mile of quiet street (no lane, LTS 1-2), the unit RouteMaker's own score
already prices in (`refine.QUIET_COST_FACTOR`: a quiet metre costs the router 2.2 times its
time). A stretch's multiplier `M` is what a metre of it costs over what a quiet metre
costs, at the rider's preset and slider position:

- **The router's cost of the road itself** (`road_multiplier`, docs/stress/stress-number.md
  section 4). Valhalla's bicycle edge cost is `time x (1 + grade + accommodation x roadway
  stress)` (sif/bicyclecost.cc, 3.9.1, `BicycleCost::EdgeCost`); the factor without the
  grade (and the surface, which is not traffic) is worked out here from the edge's own
  attributes as the trace returns them (`TRACE_ATTRIBUTES`: its class, use, lanes, cycle
  lane, shoulder, truck route, bicycle network, and the speed the graph gave it) and the
  ride's `use_roads`, and divided by the same factor for a quiet street (`quiet_factor`: a
  residential street with no lane at its default speed, urban or rural as the road is), so
  an all-quiet route reads exactly 1 (461d). A junction's and an Avoid entry's quiet metres,
  priced at 2.2 (which was measured with the grade in), are scaled by 2.2 over the quiet
  street's factor (`junction_scale`) to keep their meaning. LTS 3 and up carry the
  `use_sidepath` mark the graph writes there; LTS 4 and Avoid also the graph's top speed
  and lane count (read off the edge: its lane count is 15, and such an edge carries the
  mark whatever the live tier says). Each piece is rated and graded as the stress section
  it lies in, so a folded sliver is neither a rated island nor an unseen Avoid entry. Where
  the live tier and the graph disagree about grading (a stress edit since the last
  rebuild), the answer says `estimate`. Avoid pays its entry charge where the route enters
  it.
- **The tier's figure** (`multiplier`), where the trace gave no attributes (an older answer,
  a test double): `1 + added / 2.2` at LTS 3 and up, where `added` is the middle of the five
  modelled road types' range for the slider's `use_roads` (docs/DEVELOPMENT.md "Graded
  stress"; `ADDED`), linear between positions, and the facility class at LTS 1-2. This is
  the design's fallback and an estimate, and the answer says so (`estimate`).
- **The band edges** are read from representative roads at their own cost (`bands`), so each
  tier's typical road lands in its own band.
- **Above 80 on the slider.** The calm rate prices each tier's metres at its exposure weight
  (`refine.Analysis.score`): `+ rate x w(L)`.
- **The top of the slider (100).** There is no per-metre price; the worth rule's exchange
  is the ranking's own: `1 + 5 x w(L)` with no target, `1 + 10 x w(L)` with one (the price
  up to the target, 435 "One rule", since the answer is fitted to it), at the standard
  1 / 2 / 3 weights (`refine.WORTH_*`). LTS 1-2 are still priced by the road's own cost.

A junction counts what the ranking charges for it (461c, 461d: "today's distance-equivalent
penalty ... times its factors and the preset's intersection weight"): the junction model's
cost (`cost_ft`, the junction's own) times `refine.intersection_weight` at the slider
position (0.25 at 0, 1 from 70). At the top of the slider the worth rule's exchange stands
in, as it does for the stretches: a red junction counts its cost at the LTS 4 weight, an
orange one at the LTS 3 weight, times the exchange (`refine.stress_weight_m`), and an
unflagged one nothing.

An unrated stretch has no number: it counts in neither the calm miles nor the miles, a
junction or an Avoid entry inside it is not counted either, and a window that is all
unrated has no value.
"""

from __future__ import annotations

import bisect
from collections.abc import Sequence
from dataclasses import dataclass

# 461e: "a reasonable roll, maybe a mile or so". One setting, so it can be tuned.
WINDOW_M = 1609.344
METRES_PER_FOOT = 0.3048
# A quiet metre's cost over its time (refine.QUIET_COST_FACTOR; restated, as this package
# does not import core).
QUIET_FACTOR = 2.2
# A quiet street's roadway stress term in Valhalla's `time x (1 + accommodation x stress)`:
# the quiet metre's 2.2 less its time.
QUIET_STRESS = QUIET_FACTOR - 1.0

# The added cost per metre of LTS 3 and LTS 4, as a multiple of its time, at each `use_roads`
# the model was read at (docs/DEVELOPMENT.md "Graded stress"; docs/stress/routing-costs.md
# section 1): the middle of the five road types' range. use_roads 1.0, 0.871 and 0.486 are
# positions 0, 10 and 40 today; 0.10 is 70 (Default); 0.0 is 80 and above.
ADDED: tuple[tuple[float, float, float], ...] = (
    # (use_roads, LTS 3, LTS 4)
    (0.0, (4.75 + 12.84) / 2, (32.14 + 40.52) / 2),
    (0.10, (4.13 + 10.54) / 2, (26.08 + 32.62) / 2),
    (0.486, (2.05 + 4.06) / 2, (9.63 + 11.56) / 2),
    (0.871, (0.47 + 0.80) / 2, (2.44 + 2.94) / 2),
    (1.0, 0.0, (0.82 + 1.14) / 2),
)

# The worth rule's exchange at the top of the slider (refine.WORTH_DEFAULT; with a target,
# refine.WORTH_UP_TO_TARGET, the price of the miles up to it, OWNER-DECISIONS 435) and its
# level weights (refine.WORTH_WEIGHTS: the standard 1 / 2 / 3).
WORTH_DEFAULT = 5.0
WORTH_UP_TO_TARGET = 10.0
WORTH_WEIGHTS = {3: 1.0, 4: 2.0, 5: 3.0}

# Avoid's entry charge (presets.AVOID_ENTRY_PENALTY_S), cost seconds.
AVOID_ENTRY_S = 1800.0


@dataclass(frozen=True)
class Pricing:
    """What a ride's slider position charges, as the score needs it."""

    use_roads: float
    # Metres of detour per metre of each tier above 80 (presets.calm_rate_for), and the
    # preset's exposure weights by tier (3, 4, 5).
    rate: float = 0.0
    weights: tuple[float, float, float] = (1.0, 2.0, 3.0)
    # The top of the slider (presets.maxcalm_for), and whether the rider set a target.
    maxcalm: bool = False
    target: bool = False
    # The no-trail graph: no grading and no facility classes.
    no_trail: bool = False
    # The router's cost of a quiet metre at this ride's speed, cost seconds
    # (refine.quiet_cost_per_m), for the Avoid entry charge.
    quiet_cost_s: float = 0.44
    # How much of a junction's cost the ranking counts at this position
    # (refine.intersection_weight).
    junction_weight: float = 1.0


def _added(use_roads: float) -> tuple[float, float]:
    """LTS 3's and LTS 4's added cost per metre at a `use_roads`, linear between the
    modelled positions."""
    u = min(max(use_roads, 0.0), 1.0)
    for (u0, a3, a4), (u1, b3, b4) in zip(ADDED, ADDED[1:], strict=False):
        if u0 <= u <= u1:
            t = 0.0 if u1 == u0 else (u - u0) / (u1 - u0)
            return a3 + t * (b3 - a3), a4 + t * (b4 - a4)
    return ADDED[-1][1], ADDED[-1][2]


def facility_factor(facility: str | None, use_roads: float) -> float:
    """A calm (LTS 1-2) metre's cost over a quiet street's, by its facility class."""
    u = min(max(use_roads, 0.0), 1.0)
    if facility == "path":
        return (1.0 + 0.1 + 0.9 * u) / QUIET_FACTOR
    if facility == "protected":
        return (1.0 + (0.15 + 0.6 * u) * QUIET_STRESS) / QUIET_FACTOR
    if facility == "lane":
        return (1.0 + (0.9 + 0.05 * u) * QUIET_STRESS) / QUIET_FACTOR
    return 1.0


def multiplier(tier: int | None, facility: str | None, pricing: Pricing) -> float | None:
    """Calm metres a metre of this stretch counts for; None where it is not rated."""
    if tier is None:
        return None
    if tier <= 2:
        return 1.0 if pricing.no_trail else facility_factor(facility, pricing.use_roads)
    level = min(tier, 5)
    if pricing.maxcalm:
        worth = WORTH_UP_TO_TARGET if pricing.target else WORTH_DEFAULT
        return 1.0 + worth * WORTH_WEIGHTS[level]
    lts3, lts4 = _added(pricing.use_roads)
    added = lts3 if level == 3 or pricing.no_trail else lts4
    weight = pricing.weights[level - 3]
    return 1.0 + added / QUIET_FACTOR + pricing.rate * weight


# --- The router's own cost of a road -------------------------------------------------------
#
# Valhalla 3.9.1's bicycle costing (sif/bicyclecost.cc: `BicycleCost`'s constructor and
# `EdgeCost`), restated for the edge attributes a trace returns. Only the traffic part: the
# grade penalty, the surface factor, the turn costs and the alley charge are left out (the
# alley charge counts as Avoid's entry, the junctions by the junction model).

# The edge attributes `road_of_edge` reads, asked for in `routing.trace_leg` (Valhalla's
# baldr/attributes_controller.h names).
TRACE_ATTRIBUTES = (
    "edge.use",
    "edge.road_class",
    "edge.lane_count",
    "edge.cycle_lane",
    "edge.shoulder",
    "edge.truck_route",
    "edge.bicycle_network",
    "edge.speed_limit",
    "edge.density",
    "edge.roundabout",
    "edge.surface",
)

# Roadway stress a road class adds, times the road factor (`kRoadClassFactor`).
ROAD_CLASS_FACTOR = {
    "motorway": 1.0,
    "trunk": 0.4,
    "primary": 0.2,
    "secondary": 0.1,
    "tertiary": 0.05,
    "unclassified": 0.05,
    "residential": 0.0,
    "service_other": 0.5,
}
# The speed (km/h) an edge with no `maxspeed` is given: the transform's `default_speed` by
# class (lua/vendor/graph_upstream.lua) and, in a built-up area (`density` above
# `kMaxRuralDensity`, 8), the graph builder's urban speeds (mjolnir/speed_assigner.h,
# `urban_rc_speed`).
RURAL_SPEED = {
    "motorway": 105,
    "trunk": 90,
    "primary": 75,
    "secondary": 60,
    "tertiary": 50,
    "unclassified": 40,
    "residential": 35,
    "service_other": 25,
}
URBAN_SPEED = {
    "motorway": 89,
    "trunk": 73,
    "primary": 57,
    "secondary": 49,
    "tertiary": 40,
    "unclassified": 35,
    "residential": 30,
    "service_other": 20,
}
MAX_RURAL_DENSITY = 8
# Uses with a speed of their own (baldr/graphconstants.h `kParkingAisleSpeed`,
# `kDrivewaySpeed`, `kDriveThruSpeed`).
USE_SPEED = {"parking_aisle": 15, "driveway": 10, "drive_through": 10}
# Surfaces at or past `kPavedRough`, which lower the edge's speed.
ROUGH_SURFACES = frozenset({"paved_rough", "compacted", "dirt", "gravel", "path", "impassable"})
# What the graded tiers are given (lua/routemaker_remap.lua `GRADED_SPEED`, `GRADED_LANES`):
# the graph's top speed and lane count, so an edge with 15 lanes is a graded one.
GRADED_SPEED_KPH = 140
GRADED_LANES = 15
# Valhalla's path uses, priced by their separation from walkers, and the trail-class uses,
# which never carry the stress mark (lua/routemaker_remap.lua: "never on a trail-class way").
PATH_USES = frozenset({"cycleway", "footway", "path"})
TRAIL_USES = PATH_USES | {"steps", "pedestrian", "bridleway", "sidewalk", "mountain_bike"}
# Uses whose router cost is not traffic: stairs (priced at a walking pace) and ferries. They
# count at the tier's figure.
NOT_TRAFFIC_USES = frozenset({"steps", "ferry", "rail-ferry"})
# The tier the stress mark (`bicycle=use_sidepath`) is written from
# (lua/routemaker_remap.lua `STRESS_PENALTY_TIER`).
SIDEPATH_TIER = 3
TRUCK_STRESS = 0.5
BICYCLE_NETWORK_FACTOR = 0.95
KPH_PER_MPH = 1.609344


@dataclass(frozen=True)
class Road:
    """One traced edge's costing attributes, as the router's graph holds them."""

    use: str = "road"
    road_class: str = "residential"
    lanes: int = 1
    cycle_lane: str = "none"
    shoulder: bool = False
    truck_route: bool = False
    bike_network: bool = False
    # The tagged `maxspeed`, km/h (`edge.speed_limit`); None where the way has none.
    speed_limit_kph: float | None = None
    density: int = 0
    roundabout: bool = False
    surface: str = "paved"


def road_of_edge(edge: dict, miles: bool = False) -> Road | None:
    """An edge of a trace's answer as a `Road`; None where it carries no costing attributes
    (a router not asked for them, a test double)."""
    if "lane_count" not in edge or "road_class" not in edge:
        return None
    limit = edge.get("speed_limit")
    limit_kph = float(limit) * (KPH_PER_MPH if miles else 1.0) if _is_number(limit) else None
    lanes = edge.get("lane_count")
    density = edge.get("density")
    return Road(
        use=str(edge.get("use") or "road"),
        road_class=str(edge.get("road_class") or "residential"),
        lanes=int(lanes) if _is_number(lanes) else 1,
        cycle_lane=str(edge.get("cycle_lane") or "none"),
        shoulder=bool(edge.get("shoulder")),
        truck_route=bool(edge.get("truck_route")),
        bike_network=bool(edge.get("bicycle_network")),
        speed_limit_kph=limit_kph if limit_kph and limit_kph > 0 else None,
        density=int(density) if _is_number(density) else 0,
        roundabout=bool(edge.get("roundabout")),
        surface=str(edge.get("surface") or "paved"),
    )


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def graded(road: Road) -> bool:
    """Whether the graph gave this edge the graded tiers' top speed and lane count."""
    return road.lanes >= GRADED_LANES


def road_speed_kph(road: Road) -> int:
    """The speed the graph gave the edge (`DirectedEdge::speed`), which its roadway stress
    rises with: the graded tiers' 140, a tagged `maxspeed`, or the class's default, as the
    graph builder adjusts them (mjolnir/speed_assigner.h `SpeedAssigner::UpdateSpeed`, with
    no speed configuration, as RouteMaker builds)."""
    rough = road.surface in ROUGH_SURFACES
    # The graded speed is written as `maxspeed:practical`, which the builder takes as a
    # tagged speed: a graded turn channel is 175 km/h and a graded rough road 130.
    tagged = graded(road) or road.speed_limit_kph is not None
    if graded(road):
        speed = GRADED_SPEED_KPH
    elif road.speed_limit_kph is not None:
        speed = round(road.speed_limit_kph)
    else:
        speed = RURAL_SPEED.get(road.road_class, 25)
    if road.use in ("ramp", "turn_channel"):
        # A link keeps its speed but for these factors (`kTurnChannelFactor`, with
        # `infer_turn_channels` on as valhalla/*.json set it; `kRampFactor`,
        # `kRampDensityFactor`), and is adjusted no further.
        if road.use == "turn_channel":
            return int(speed * 1.25 + 0.5)
        if tagged:
            return speed
        busy = road.road_class in ("motorway", "trunk", "primary")
        factor = 0.8 if busy and road.density > MAX_RURAL_DENSITY else 0.85
        return int(speed * factor + 0.5)
    if tagged:
        if rough:
            speed = speed - 10 if speed >= 50 else speed - 5 if speed > 15 else speed
        return speed
    # The trace's `density` is the edge's average, not the start node's density the builder's
    # urban test read, so on an edge that crosses the urban line the two can differ.
    if road.density > MAX_RURAL_DENSITY:
        speed = URBAN_SPEED.get(road.road_class, speed)
    if road.roundabout:
        speed = int(speed * 0.5 + 0.5)
    speed = USE_SPEED.get(road.use, speed)
    if rough:
        speed //= 2
    return speed


def _road_factor(u: float) -> float:
    return 1.5 - u if u >= 0.5 else 2.0 - u * 2.0


def _speed_penalty(speed: int, u: float) -> float:
    if speed <= 0:
        return 0.0
    if speed <= 40:
        base = speed / 40.0
    elif speed <= 65:
        base = speed / 25.0 - 0.6
    else:
        base = speed / 50.0 + 0.7
    return (base - 1.0) * ((1.0 - u) * 0.75 + 0.25) + 1.0


def _lane_factor(road: Road, u: float) -> float:
    """`cyclelane_factor_`: a cycle lane's class, else a shoulder."""
    if road.cycle_lane == "shared":
        return 0.9 + u * 0.05
    if road.cycle_lane == "dedicated":
        return 0.4 + u * 0.45
    if road.cycle_lane == "separated":
        return 0.15 + u * 0.6
    return 0.7 + u * 0.2 if road.shoulder else 1.0


def _path_factor(road: Road, u: float) -> float:
    """`path_cyclelane_factor_`: how far a path keeps cyclists from walkers."""
    if road.cycle_lane == "dedicated":
        return 0.1 + u * 0.9
    if road.cycle_lane == "separated":
        return u * 0.8
    return 0.2 + u


def edge_factor(road: Road, tier: int, use_roads: float) -> float:
    """Valhalla's cost of a metre of the edge as a multiple of its time, grade and surface
    left out: `1 + accommodation x roadway stress`. The stress mark is the graph's from
    LTS 3, never on a trail-class way; a graded edge carries it whatever `tier` says (the
    two are written together, and a stress edit changes the tier before a rebuild)."""
    u = min(max(use_roads, 0.0), 1.0)
    stress = 1.0
    accommodation = 1.0
    if road.use in PATH_USES:
        accommodation = _path_factor(road, u)
    elif road.use == "living_street":
        stress = 0.2 + u * 0.8
    elif road.use == "track":
        stress = 0.5 + u
    else:
        accommodation = _lane_factor(road, u)
        road_factor = _road_factor(u)
        if road.lanes > 1:
            stress += (road.lanes - 1) * 0.05 * road_factor
        if road.truck_route:
            stress += TRUCK_STRESS
        stress += road_factor * ROAD_CLASS_FACTOR.get(road.road_class, 0.5)
        stress *= _speed_penalty(road_speed_kph(road), u)
    if (tier >= SIDEPATH_TIER or graded(road)) and road.use not in TRAIL_USES:
        accommodation += 3.0 * (1.0 - u)
    if road.bike_network:
        accommodation *= BICYCLE_NETWORK_FACTOR
    return 1.0 + accommodation * stress


# The quiet street the scale's 1 is (461d: "1.0 = all calm riding"): a residential street with
# no lane at its default speed, urban (density over 8, 20 mph (30 km/h)) or rural
# (22 mph (35 km/h)).
QUIET_URBAN = Road(road_class="residential", density=MAX_RURAL_DENSITY + 1)
QUIET_RURAL = Road(road_class="residential", density=0)


def quiet_factor(use_roads: float, urban: bool = True) -> float:
    """The router's cost of a metre of quiet street as a multiple of its time, grade left
    out, at this `use_roads`: what a road's own cost is divided by. (`QUIET_FACTOR`'s 2.2
    was measured with the grade in, so dividing by it would put a quiet street at 0.8 to
    0.9.)"""
    return edge_factor(QUIET_URBAN if urban else QUIET_RURAL, 1, use_roads)


def junction_scale(pricing: Pricing) -> float:
    """What a junction's or an Avoid entry's quiet metres (priced at `QUIET_FACTOR`) are
    multiplied by on the own-cost scale, so they keep their meaning there: 2.2 over the
    urban quiet street's factor."""
    return QUIET_FACTOR / quiet_factor(pricing.use_roads)


def disagrees(tier: int, road: Road, pricing: Pricing) -> bool:
    """Whether the live tier and the graph disagree about grading: a graded edge the live
    table rates under LTS 4, or an LTS 4 or Avoid way the graph did not grade (a stress
    edit since the last rebuild, or a way the transform could not mark)."""
    if graded(road):
        return tier < 4
    return tier >= 4 and not pricing.no_trail and road.use not in TRAIL_USES


def road_multiplier(
    tier: int | None, facility: str | None, road: Road | None, pricing: Pricing
) -> tuple[float | None, bool]:
    """Calm metres a metre of this edge counts for, and whether that is its own cost as the
    graph prices it (False: the tier's figure stands in, as the trace gave no attributes, or
    the live tier and the graph disagree, `disagrees`). At the top of the slider LTS 3 and
    up take the worth rule's figure, which is the ranking's own price."""
    if tier is None:
        return None, True
    if road is None:
        return multiplier(tier, facility, pricing), False
    level = min(tier, 5)
    agreed = not disagrees(level, road, pricing)
    if road.use in NOT_TRAFFIC_USES or (pricing.maxcalm and level >= 3):
        return multiplier(tier, facility, pricing), agreed
    urban = road.density > MAX_RURAL_DENSITY
    own = edge_factor(road, level, pricing.use_roads) / quiet_factor(pricing.use_roads, urban)
    if level >= 3:
        own += pricing.rate * pricing.weights[level - 3]
    return own, agreed


def avoid_entry_m(pricing: Pricing) -> float:
    """Avoid's entry charge as quiet metres at this ride's speed."""
    return AVOID_ENTRY_S / pricing.quiet_cost_s if pricing.quiet_cost_s > 0 else 0.0


def junction_m(cost_ft: float, severity: str | None, flagged: bool, pricing: Pricing) -> float:
    """Calm metres a junction counts for at this ride's position."""
    cost_m = max(cost_ft, 0.0) * METRES_PER_FOOT
    if pricing.maxcalm:
        worth = WORTH_UP_TO_TARGET if pricing.target else WORTH_DEFAULT
        level = {"red": 4, "orange": 3}.get(severity or "") if flagged else None
        return worth * WORTH_WEIGHTS[level] * cost_m if level else 0.0
    return cost_m * pricing.junction_weight


# A band edge sits at least this far above a quiet street's 1, so an all-quiet route never
# reads as LTS 3 where LTS 3 costs nothing extra (at 0 on the slider).
MIN_BAND_GAP = 0.05


# The representative roads the band edges are read from (review S3: a 25 mph LTS 3 street must
# not be said as "LTS 1 to 2 level" over a road the map colours LTS 3), all urban, priced by
# the router's own cost at the ride's position:
# - the busiest typical calm road and the calmest typical LTS 3 one: a 25 mph (40 km/h)
#   collector with one lane each way and no bike lane, at LTS 2 and at LTS 3;
# - the busiest typical LTS 3 road: a 40 mph (64 km/h) primary, two lanes each way;
# - the calmest LTS 4 road: a graded residential street (the graph's top speed and lanes), or,
#   on the no-trail graph, which grades nothing, a 45 mph (72 km/h) trunk, three lanes each way.
BAND_COLLECTOR = Road(road_class="tertiary", speed_limit_kph=40, density=MAX_RURAL_DENSITY + 1)
BAND_ARTERIAL = Road(
    road_class="primary", lanes=2, speed_limit_kph=64, density=MAX_RURAL_DENSITY + 1
)
BAND_GRADED = Road(road_class="residential", lanes=GRADED_LANES, density=MAX_RURAL_DENSITY + 1)
BAND_TRUNK = Road(road_class="trunk", lanes=3, speed_limit_kph=72, density=MAX_RURAL_DENSITY + 1)


def bands(pricing: Pricing) -> tuple[float, float]:
    """Where the words change (docs/stress/stress-number.md "Words as a guide"): halfway
    between the busiest typical calm road and the calmest typical LTS 3 road, and halfway
    between the busiest typical LTS 3 road and the calmest LTS 4 one, each at its own cost
    (`BAND_*`), so each tier's typical road lands in its own band. Where LTS 3 costs no more
    than LTS 2 (0 on the slider) there is no LTS 3 band: both edges are the upper one."""

    def at(road: Road, tier: int) -> float:
        return road_multiplier(tier, "none", road, pricing)[0] or 1.0

    calm_top, lts3_low = at(BAND_COLLECTOR, 2), at(BAND_COLLECTOR, 3)
    lts4_low = at(BAND_TRUNK if pricing.no_trail else BAND_GRADED, 4)
    high = max((at(BAND_ARTERIAL, 3) + lts4_low) / 2, 1.0 + MIN_BAND_GAP)
    low = (calm_top + lts3_low) / 2
    if lts3_low - calm_top < MIN_BAND_GAP or low < 1.0 + MIN_BAND_GAP:
        low = high
    return low, high


@dataclass(frozen=True)
class Step:
    """One stretch of the route at its own multiplier (None: not rated)."""

    from_m: float
    to_m: float
    ratio: float | None
    tier: int | None


@dataclass(frozen=True)
class Point:
    """Calm metres counted at one place: a junction's cost, or Avoid's entry charge."""

    m: float
    calm_m: float
    kind: str  # "junction" or "avoid_entry"
    severity: str | None = None


def steps_of(spans: Sequence[dict], pricing: Pricing) -> list[Step]:
    """The route's stress sections (`routing.stress_spans`) at their multipliers, adjacent
    equal ones joined."""
    out: list[Step] = []
    for span in spans:
        lo, hi = float(span["from_m"]), float(span["to_m"])
        if hi <= lo:
            continue
        tier = span.get("tier")
        ratio = multiplier(tier, span.get("facility"), pricing)
        if out and out[-1].to_m == lo and out[-1].ratio == ratio and out[-1].tier == tier:
            out[-1] = Step(out[-1].from_m, hi, ratio, tier)
        else:
            out.append(Step(lo, hi, ratio, tier))
    return out


# One traced piece as the score reads it, in route order: (metres, tier or None, facility or
# None, its edge's `Road` or None).
Costed = tuple[float, int | None, str | None, Road | None]


def piece_steps(
    pieces: Sequence[Costed], pricing: Pricing, sections: Sequence[Step] | None = None
) -> tuple[list[Step], bool]:
    """The route's traced pieces, each at its own road's multiplier, adjacent equal ones
    joined; and whether every rated piece was priced by its own cost as the graph prices it
    (False: some took the tier's figure, or its live tier and the graph disagree). With
    `sections`, each piece is rated and graded as its section's tier
    (`with_section_tiers`); whether the graph agrees is still read against its own."""
    out: list[Step] = []
    exact = True
    at = 0.0
    shown = with_section_tiers(pieces, sections) if sections is not None else pieces
    for (metres, own_tier, _f, road), (_m, tier, facility, _r) in zip(pieces, shown, strict=True):
        if metres <= 0:
            continue
        ratio, own = road_multiplier(tier, facility, road, pricing)
        if ratio is not None and road is not None and own_tier is not None:
            own = not disagrees(min(own_tier, 5), road, pricing)
        exact = exact and own
        lo, at = at, at + metres
        if out and out[-1].ratio == ratio and out[-1].tier == tier:
            out[-1] = Step(out[-1].from_m, at, ratio, tier)
        else:
            out.append(Step(lo, at, ratio, tier))
    return out, exact


def with_section_tiers(pieces: Sequence[Costed], sections: Sequence[Step]) -> list[Costed]:
    """Each piece with the tier of the section its middle lies in (None in an unrated one or
    in a hole), so the score rates and grades what the map colours: a piece shorter than
    `routing.MIN_SPAN_M` folded into its neighbour is not a rated island in an unrated
    section, nor an Avoid entry the chart does not show (review S1)."""
    starts = [s.from_m for s in sections]
    out: list[Costed] = []
    at = 0.0
    for metres, _tier, facility, road in pieces:
        middle = at + metres / 2
        at += metres
        i = bisect.bisect_right(starts, middle) - 1
        inside = 0 <= i < len(sections) and sections[i].from_m <= middle <= sections[i].to_m
        out.append((metres, sections[i].tier if inside else None, facility, road))
    return out


def points_of(
    steps: Sequence[Step], events: Sequence | None, pricing: Pricing, scale: float = 1.0
) -> list[Point]:
    """The calm metres counted at a place, in route order: every junction the model
    charges for (flagged or not), and each entry into Avoid. `scale` puts their quiet
    metres on the own-cost scale (`junction_scale`)."""
    out: list[Point] = []
    starts = [s.from_m for s in steps]
    for event in events or ():
        flagged = bool(getattr(event, "flagged", False))
        severity = getattr(event, "severity", None) if flagged else None
        counted = scale * junction_m(
            float(getattr(event, "cost_ft", 0.0) or 0.0), severity, flagged, pricing
        )
        if counted > 0 and _rated_at(steps, starts, float(event.m)):
            out.append(Point(float(event.m), counted, "junction", severity))
    entry = scale * avoid_entry_m(pricing)
    previous: Step | None = None
    for step in steps:
        joined = previous is not None and previous.tier == 5 and previous.to_m >= step.from_m
        if step.tier == 5 and not joined and entry > 0:
            out.append(Point(step.from_m, entry, "avoid_entry"))
        previous = step
    return sorted(out, key=lambda p: p.m)


def _rated_at(steps: Sequence[Step], starts: Sequence[float], m: float) -> bool:
    """Whether a place lies on a rated stretch (either side of a joint will do); `starts`
    are the steps' `from_m`."""
    i = bisect.bisect_right(starts, m) - 1
    for j in (i, i - 1):
        if 0 <= j < len(steps) and steps[j].from_m <= m <= steps[j].to_m:
            if steps[j].ratio is not None:
                return True
    return False


class Rolling:
    """The calm metres and rated metres up to any distance, for windows in O(log n)."""

    def __init__(self, steps: Sequence[Step], points: Sequence[Point]) -> None:
        self.edges: list[float] = [0.0]
        self.calm: list[float] = [0.0]
        self.rated: list[float] = [0.0]
        self.ratios: list[float | None] = []
        for step in steps:
            if step.from_m > self.edges[-1]:
                # A hole between sections: not rated.
                self._push(step.from_m, None)
            self._push(step.to_m, step.ratio)
        self.point_m = [p.m for p in points]
        self.point_sum = [0.0]
        for p in points:
            self.point_sum.append(self.point_sum[-1] + p.calm_m)

    def _push(self, to_m: float, ratio: float | None) -> None:
        length = to_m - self.edges[-1]
        self.edges.append(to_m)
        self.ratios.append(ratio)
        self.calm.append(self.calm[-1] + (length * ratio if ratio is not None else 0.0))
        self.rated.append(self.rated[-1] + (length if ratio is not None else 0.0))

    @property
    def end_m(self) -> float:
        return self.edges[-1]

    def upto(self, x: float) -> tuple[float, float]:
        """(calm metres, rated metres) from the start to `x`."""
        if x <= 0:
            return 0.0, 0.0
        if x >= self.edges[-1]:
            return self.calm[-1], self.rated[-1]
        i = bisect.bisect_right(self.edges, x) - 1
        ratio = self.ratios[i]
        part = x - self.edges[i]
        return (
            self.calm[i] + (part * ratio if ratio is not None else 0.0),
            self.rated[i] + (part if ratio is not None else 0.0),
        )

    def points_between(self, lo: float, hi: float) -> float:
        a = bisect.bisect_left(self.point_m, lo)
        b = bisect.bisect_right(self.point_m, hi)
        return self.point_sum[b] - self.point_sum[a]

    def at(self, x: float, window_m: float = WINDOW_M) -> float | None:
        """Calm miles per mile over the window centred on `x`, cut at the route's ends;
        None where the window holds no rated metre."""
        lo = max(0.0, x - window_m / 2)
        hi = min(self.end_m, x + window_m / 2)
        calm_hi, rated_hi = self.upto(hi)
        calm_lo, rated_lo = self.upto(lo)
        rated = rated_hi - rated_lo
        if rated <= 0:
            return None
        return (calm_hi - calm_lo + self.points_between(lo, hi)) / rated

    def total_calm_m(self) -> float:
        return self.calm[-1] + self.point_sum[-1]

    def total_rated_m(self) -> float:
        return self.rated[-1]


def _built(
    spans: Sequence[dict],
    events: Sequence | None,
    pricing: Pricing,
    pieces: Sequence[Costed] | None,
) -> tuple[Rolling, list[Step], list[Point], bool]:
    """The rolling sums, the sections as sent (each at its own figure), the points counted,
    and whether every rated metre was priced by its own road's cost.

    With the traced `pieces` (stress-number.md section 4: each road priced by its own
    routing cost) the sums run over every piece at its own multiplier, graded as its
    section's tier (`with_section_tiers`), and a section's figure is the mean over it (its
    calm metres over its rated metres), so the step line keeps one step a section. The
    junctions and Avoid entries are read against the sections, put on the own-cost scale
    (`junction_scale`). Without the pieces each section takes its tier's figure."""
    sections = steps_of(spans, pricing)
    if pieces is None:
        points = points_of(sections, events, pricing)
        return Rolling(sections, points), sections, points, False
    fine, exact = piece_steps(pieces, pricing, sections)
    points = points_of(sections, events, pricing, junction_scale(pricing))
    rolling = Rolling(fine, points)
    sent = []
    for s in sections:
        calm_hi, rated_hi = rolling.upto(s.to_m)
        calm_lo, rated_lo = rolling.upto(s.from_m)
        rated = rated_hi - rated_lo
        mean = (calm_hi - calm_lo) / rated if rated > 0 and s.tier is not None else None
        sent.append(Step(s.from_m, s.to_m, mean, s.tier))
    return rolling, sent, points, exact


def peak_index(
    spans: Sequence[dict],
    events: Sequence | None,
    pricing: Pricing,
    sample_m: Sequence[float],
    window_m: float = WINDOW_M,
    pieces: Sequence[Costed] | None = None,
) -> int | None:
    """The sample whose window scores highest (the first of a tie), read over every sample
    before a long route is thinned, so the thinned answer keeps it."""
    rolling = _built(spans, events, pricing, pieces)[0]
    best: int | None = None
    best_r = -1.0
    for i, m in enumerate(sample_m):
        r = rolling.at(m, window_m)
        if r is not None and r > best_r:
            best, best_r = i, r
    return best


def score(
    spans: Sequence[dict],
    events: Sequence | None,
    pricing: Pricing,
    sample_m: Sequence[float],
    window_m: float = WINDOW_M,
    pieces: Sequence[Costed] | None = None,
) -> dict:
    """The rolling score at each of `sample_m`, the sections at their own multipliers, the
    points counted, the route's total, and where the words change: the route answer's
    `profile.calm` (core.api.ProfileCalmOut). `pieces` are the traced pieces with their
    edges' attributes, for each road's own cost; without them, or where a piece has none,
    the tier's figure stands in and `estimate` is true."""
    rolling, steps, points, exact = _built(spans, events, pricing, pieces)
    low, high = bands(pricing)
    ratio = [rolling.at(m, window_m) for m in sample_m]
    return {
        "window_m": round(window_m),
        "ratio": [_round(r) for r in ratio],
        "steps": [
            {
                "from_m": round(s.from_m),
                "to_m": round(s.to_m),
                "ratio": _round(s.ratio),
                "tier": s.tier,
            }
            for s in steps
        ],
        # Only what the chart marks: the flagged junctions and the Avoid entries. Every
        # junction is in `ratio` and the total (operations review: the answer's size).
        "points": [
            {"m": round(p.m), "calm_m": round(p.calm_m), "kind": p.kind, "severity": p.severity}
            for p in points
            if p.kind != "junction" or p.severity is not None
        ],
        "total_calm_m": round(rolling.total_calm_m()),
        "rated_m": round(rolling.total_rated_m()),
        "junctions_counted": events is not None,
        "bands": [_round(low), _round(high)],
        "estimate": not exact,
    }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 2)
