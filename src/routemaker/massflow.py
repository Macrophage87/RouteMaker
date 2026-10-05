"""How many riders a road carries per minute: the Mass Ride capacity (PLAN.md,
"The headline number: modelled throughput").

The owner, 2026-10-04: "The focus is on carrying capacity, not LTS here. ...
The headline color should be riders per minute." (OWNER-DECISIONS 325), in
riders per minute at 6-8 mph (326), with the bands 60, 120 and 200 (327).

The model is the plan's working model (OWNER-DECISIONS 394: accepted as the
working model, its sources pending FOLLOWUP-FLOW-CALIBRATION), from the owner's
counts of three DC Bike Party rides (item 173,
`reports/owner/cyclist_packing_density.md`; indicative, item 175):

    riders a minute = 60 x safe density x utilisation x usable width x pace

- safe density 0.37 riders per square metre: the packing at a pinch, turn or
  signal queue, which is the state a road is judged by ("a ride flows at its
  narrowest point");
- utilisation 0.7: a pack bunches toward part of the road rather than filling it;
- pace 1.9 m/s (4.3 mph): the pace that density was seen at. The flow is
  conserved through a slowdown, so at the 6-8 mph cruise the same riders pass
  each second over more road (looser), and the headline stays this figure.

That is 29.5 riders a minute for every metre of usable width: about 99 per 11 ft
(3.35 m) lane. The constants are `routemaker.flow`'s, named here once so the
front end's bands need no second copy.

USABLE WIDTH (OWNER-DECISIONS 404; `usable_width_m`, the one function) is the
width a corked group has in the direction it rides:

- A corked ride holds the cross streets at each junction (the corkers); it does
  not hold the oncoming traffic, and a DC Bike Party keeps to its own side of a
  two-way street. So on a two-way street the group has its own direction's travel
  lanes and the painted bike lane on its side, not the oncoming lanes and not a
  shared centre turn lane. A segment is drawn once for both directions, so its
  figure is the NARROWER direction's (a ride flows at its narrowest point, and the
  map does not know which way a ride will go). A one-way street gives the group
  every travel lane and every painted lane that runs with it (a contraflow lane
  runs against it and is not counted). A street of one shared lane (DC's
  "bidirectional" lane, OSM `lanes=1` on a two-way way) is that lane.
- Parked cars narrow it (404 (1)): a parking lane is never usable, and where a
  painted bike lane runs beside parking a door zone (`DOOR_ZONE_M`, 3.5 ft) of the
  bike lane is kept out. No margin is taken where there is no bike lane: the
  travel lane's own width already starts at the parked cars' edge.
- In DC, from the District's own Roadway Block (404 (3): "Absolutely. That's why I
  focused on DC."): the travel lanes by direction times the block's lane width,
  plus the painted bike lanes, less door zones. DC records the parking lanes'
  width apart from the travel lanes' (`TOTALPARKINGLANEWIDTH`,
  `TOTALTRAVELLANEWIDTH`), so curb to curb less the parked cars is the travel and
  bike lanes. DC's widths are totals over the block's lanes; the parser
  (`agency_roads.parse_dc_roadway_block`) has already divided them per lane.
  Reversible lanes count as ZERO (OWNER-DECISIONS 405, the safe, narrower reading):
  the Roadway Block's `TOTALTRAVELLANESREVERSIBLE` is stale where the lanes were
  removed (Connecticut Ave NW's ended in 2020), so a block's reversible lanes are
  counted only where a reviewed allowlist (`DcRules.verified_reversible_blocks`,
  empty for now) names it, and never on a street `DcRules.ended_reversible_streets`
  names (Connecticut Ave NW). A block with a lane width of `DcRules.wide_lane_ft`
  (16 ft) or more and no parking lane is read at `DcRules.wide_lane_cap_ft` (11
  ft) a lane (OWNER-DECISIONS 407 (3): probably shared parking and driving lanes).
  Both are provisional (407), to revisit with FOLLOWUP-FLOW-CALIBRATION. Bus lanes are in DC's
  counts and are counted (a corked ride uses them). A way along several blocks
  takes the narrowest block's figure.
- Elsewhere, and in DC where the blocks record no lane count or no plausible lane
  width: OpenStreetMap. A mapped carriageway `width` (curb to curb) less the parked
  cars (`parking_width_m`: 8 ft (2.4 m) a side of parallel parking where OSM says
  parking but no width) and door zones, halved on a two-way way; otherwise the
  lanes in the direction times 11 ft plus the painted lane on that side, less a
  door zone where it runs beside parking (lanes are travel lanes, so no parking is
  taken from them).

Protected lanes are never usable (OWNER-DECISIONS 127). Grade, surface and turns
are reductions the route applies (part 2); this is the flat, straight, clear-road
figure, which is what the map is coloured by (`flow.level_riders_per_min`).

Pure functions of a way's tags and its District blocks: the rebuild writes the
answer onto `segment.mass_usable_width_m` (`pipeline.run`), and nothing reads the
tags again.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from . import flow
from .agency_roads import BIKE_BUFFERED, BIKE_LANE, DC_AGENCY, DIRECTIONS, METRES_PER_FOOT
from .tags import PAINTED_CYCLEWAY, SIDES, cycleway_sides, is_oneway, parse_int, parse_width_m

# The working model's constants are `routemaker.flow`'s (copied verbatim from the
# elevation-chart branch, wip/elevation-chart 27cddab: one model, not two).
SAFE_DENSITY_PER_M2 = flow.DENSITY_PER_M2
UTILISATION = flow.UTILISATION
PACE_MS = flow.PACE_MS
# Riders a minute for each metre of usable width.
RPM_PER_METRE = flow.level_riders_per_min(1.0)

# One travel lane, 11 ft: the plan's figure, and the width a lane is read at where
# no width is mapped.
LANE_WIDTH_M = flow.LANE_WIDTH_M
# A painted bike lane's width where none is surveyed: 5 ft, the usual minimum
# beside a curb (`stress.DECENT_LANE_MIN_M`).
PAINTED_LANE_DEFAULT_M = 1.5

# The door zone kept out of a painted bike lane that runs beside parked cars
# (OWNER-DECISIONS 404 (1)): 3.5 ft (1.07 m), the swing of an opened car door. An
# owner-confirmable figure.
DOOR_ZONE_M = round(3.5 * METRES_PER_FOOT, 3)

# The width parked cars take from a mapped carriageway, a side, where OSM says
# parking and gives no width: 8 ft (2.4 m) parallel, about 15 ft (4.5 m) angled
# and 16 ft (5 m) end-on; a car half on the kerb takes half. Owner-confirmable.
PARKING_WIDTH_M = {"parallel": 2.4, "diagonal": 4.5, "perpendicular": 5.0}
# The `parking:*` values that put no car on the carriageway (`tags.has_parking_lane`
# reads the same idiom): none, recorded elsewhere, on the pavement, in bays off it.
PARKING_ABSENT = frozenset(
    {
        "no",
        "none",
        "separate",
        "no_parking",
        "no_stopping",
        "no_standing",
        "fire_lane",
        "on_kerb",
        "street_side",
    }
)

# The DC lane widths a block's figure is believed between, feet: narrower is a
# data error (eleven blocks read 1 to 4 ft), and the way is read from OSM instead.
DC_MIN_LANE_FT = 6.0
DC_MAX_LANE_FT = 20.0


@dataclass(frozen=True)
class DcRules:
    """The reviewed, provisional assumptions about the District's Roadway Block
    (OWNER-DECISIONS 405, 407; to revisit with FOLLOWUP-FLOW-CALIBRATION). The
    rebuild builds one from `settings.MASS_RIDE_DC_*`; the defaults are the same.

    - `wide_lane_ft` / `wide_lane_cap_ft`: a block recording a lane width of at
      least `wide_lane_ft` and no parking lane is read at `wide_lane_cap_ft` a lane
      (such a "lane" is likely a shared parking and driving lane).
    - `verified_reversible_blocks`: BLOCKKEYs of blocks verified to still operate
      reversible lanes. Empty: reversible lanes count as zero.
    - `ended_reversible_streets`: DC `ROUTENAME`s whose reversible lanes have
      ended, so the layer's count is stale; never counted, even if allowlisted.
    """

    wide_lane_ft: float = 16.0
    wide_lane_cap_ft: float = 11.0
    verified_reversible_blocks: frozenset = frozenset()
    ended_reversible_streets: frozenset = frozenset({"CONNECTICUT AVE NW"})

    def reversible_lanes(self, block) -> int:
        """The block's reversible lanes that count: zero unless verified."""
        count = block.lanes.get("reversible", 0)
        if not count or (block.name or "").strip().upper() in self.ended_reversible_streets:
            return 0
        return count if block.block_key in self.verified_reversible_blocks else 0


DC_RULES = DcRules()

# The carriageway widths a mapped `width` is believed between: narrower is a typo
# or a lane count, wider a dual carriageway mapped as one way.
MIN_MAPPED_WIDTH_M = 2.4
MAX_MAPPED_WIDTH_M = 40.0

# Total travel lanes, both directions, where neither `lanes` nor the classifier's
# reading says. A one-way way is read at half (at least one). Conservative: an
# untagged street is a plain two-lane street, an alley or service way one lane.
DEFAULT_LANES = {
    "motorway": 4,
    "motorway_link": 2,
    "trunk": 4,
    "trunk_link": 2,
    "primary": 4,
    "primary_link": 2,
    "secondary": 2,
    "secondary_link": 1,
    "tertiary": 2,
    "tertiary_link": 1,
    "unclassified": 2,
    "residential": 2,
    "living_street": 2,
    "service": 1,
    "track": 1,
}
# A way that is a path, not a street: its width where none is mapped. A path is
# shared, so a ride has all of it.
DEFAULT_PATH_WIDTH_M = {
    "cycleway": 3.0,
    "path": 2.5,
    "footway": 2.0,
    "pedestrian": 4.0,
    "bridleway": 2.5,
    "steps": 1.5,
}
# The smallest usable width a way is given: a single bicycle's lane, not nothing.
MIN_USABLE_WIDTH_M = 1.5
MAX_USABLE_WIDTH_M = 40.0

# The side of a two-way road each direction rides on (right-hand traffic): the
# way's own direction keeps right, against it the left.
_SIDE_OF = {"forward": "right", "backward": "left"}
_PAINTED_RANKS = (BIKE_LANE, BIKE_BUFFERED)
_SIDE_KEYS = ("cycleway:left", "cycleway:right", "cycleway:both")


def parking_width_m(tags: Mapping[str, str]) -> dict[str, float]:
    """The carriageway width parked cars take on each side (`left`, `right`),
    metres, from OSM's `parking:*` tags (the current `parking:<side>` scheme and the
    older `parking:lane:<side>`, most specific first); 0 where no tag puts a car
    there. An unknown value is read as parallel parking (the narrower reading)."""
    out = {}
    for side in SIDES:
        value = None
        for key in (
            f"parking:{side}",
            "parking:both",
            f"parking:lane:{side}",
            "parking:lane:both",
            "parking:lane",
        ):
            if tags.get(key):
                value = tags[key].strip().lower()
                break
        if value is None or value in PARKING_ABSENT:
            out[side] = 0.0
            continue
        orientation = (
            tags.get(f"parking:{side}:orientation") or tags.get("parking:both:orientation") or ""
        ).strip()
        if value in PARKING_WIDTH_M:
            orientation = value
        width = PARKING_WIDTH_M.get(orientation, PARKING_WIDTH_M["parallel"])
        out[side] = width / 2 if value == "half_on_kerb" else width
    return out


def _dc_block_width_m(block, rules: DcRules = DC_RULES) -> float | None:
    """One District block's usable width (the module docstring), metres, or None
    where it records no lanes or no plausible lane width."""
    if getattr(block, "agency", None) != DC_AGENCY:
        return None
    lane_ft = block.lane_width_ft
    if not lane_ft or not DC_MIN_LANE_FT <= lane_ft <= DC_MAX_LANE_FT:
        return None
    if lane_ft >= rules.wide_lane_ft and block.parking_lanes == 0:
        lane_ft = min(lane_ft, rules.wide_lane_cap_ft)
    lane_m = lane_ft * METRES_PER_FOOT
    bike_m = block.bike_width_ft * METRES_PER_FOOT if block.bike_width_ft else None

    def painted(direction: str) -> float:
        """The painted bike lane in a direction, less its door zone beside parking."""
        if block.bike.get(direction) not in _PAINTED_RANKS:
            return 0.0
        width = bike_m or PAINTED_LANE_DEFAULT_M
        if direction in block.bike_beside_parking:
            width -= DOOR_ZONE_M
        return max(width, 0.0)

    lanes = block.lanes
    ib, ob = lanes.get("ib", 0), lanes.get("ob", 0)
    reversible = rules.reversible_lanes(block)
    shared = lanes.get("bidirectional", 0)
    total = lanes.get("total", 0)
    one_way = block.way == "one" or (block.way is None and (ib == 0) != (ob == 0))
    if one_way:
        through = (ib + ob + reversible + shared) or total
        if not through:
            return None
        bikes = sorted(painted(direction) for direction in DIRECTIONS)
        if block.contraflow and any(bikes):
            # The contraflow lane runs against the ride: the wider is dropped.
            bikes = bikes[:-1]
        return through * lane_m + sum(bikes)
    if ib or ob:
        return min(
            (lanes.get(direction, 0) + reversible // 2) * lane_m + painted(direction)
            for direction in DIRECTIONS
            if lanes.get(direction, 0)
        )
    if shared or total:
        # One shared lane is the ride's (oncoming cars wait as on any one-lane
        # street); a block with only a total gives each direction half of it.
        through = shared or max(1, total // 2)
        return through * lane_m + min(painted(direction) for direction in DIRECTIONS)
    return None


def _osm_lanes(
    tags: Mapping[str, str], per_direction: int | None, oneway: bool, highway: str
) -> tuple[int, int] | None:
    """Travel lanes (forward, backward) from the tags, else the classifier's through
    lanes a direction, else the class default; backward is 0 on a one-way way.
    None where the class has no default."""
    total = parse_int(tags.get("lanes"))
    forward = parse_int(tags.get("lanes:forward"))
    backward = parse_int(tags.get("lanes:backward"))
    if oneway:
        for count in (total, forward, per_direction):
            if count is not None and count >= 1:
                return count, 0
        default = DEFAULT_LANES.get(highway)
        return None if default is None else (max(1, default // 2), 0)
    if forward and backward:
        return forward, backward
    if total is not None and total >= 1:
        if forward and total > forward:
            return forward, total - forward
        if backward and total > backward:
            return total - backward, backward
        half = max(1, total // 2)
        return half, half
    if per_direction is not None and per_direction >= 1:
        return per_direction, per_direction
    default = DEFAULT_LANES.get(highway)
    if default is None:
        return None
    half = max(1, default // 2)
    return half, half


def _osm_width_m(tags: Mapping[str, str], per_direction_lanes: int | None) -> float | None:
    """The OSM reading of `usable_width_m` (the module docstring)."""
    highway = tags.get("highway") or ""
    mapped = parse_width_m(tags.get("width"))
    if mapped is not None and not MIN_MAPPED_WIDTH_M <= mapped <= MAX_MAPPED_WIDTH_M:
        mapped = None
    if highway in DEFAULT_PATH_WIDTH_M:
        return mapped if mapped is not None else DEFAULT_PATH_WIDTH_M[highway]
    oneway = is_oneway(tags)
    parking = parking_width_m(tags)
    sides = cycleway_sides(dict(tags))

    def painted(side: str) -> tuple[float, float]:
        """(the painted lane's width, its door zone) on a side; (0, 0) with none."""
        lane = sides[side]
        if lane.value not in PAINTED_CYCLEWAY:
            return 0.0, 0.0
        if oneway and (
            lane.value == "opposite_lane" or tags.get(f"cycleway:{side}:oneway") == "-1"
        ):
            return 0.0, 0.0  # a contraflow lane runs against the ride
        width = lane.width_m or PAINTED_LANE_DEFAULT_M
        return width, (min(DOOR_ZONE_M, width) if parking[side] else 0.0)

    bike = {side: painted(side) for side in SIDES}
    if oneway and not any(tags.get(key) for key in _SIDE_KEYS) and bike["left"][0]:
        # A bare `cycleway=lane` on a one-way street is one lane, not one a side.
        bike["left"] = (0.0, 0.0)
    if mapped is not None:
        # The mapped width is curb to curb: the parked cars and door zones come out.
        # A two-way street of one shared lane (`lanes=1`) is the ride's whole.
        carriageway = mapped - sum(parking.values())
        if oneway or parse_int(tags.get("lanes")) == 1:
            return carriageway - sum(door for _width, door in bike.values())
        return min(carriageway / 2 - bike[_SIDE_OF[d]][1] for d in ("forward", "backward"))
    lanes = _osm_lanes(tags, per_direction_lanes, oneway, highway)
    if lanes is None:
        return None
    if oneway:
        return lanes[0] * LANE_WIDTH_M + sum(width - door for width, door in bike.values())
    return min(
        count * LANE_WIDTH_M + bike[_SIDE_OF[direction]][0] - bike[_SIDE_OF[direction]][1]
        for count, direction in zip(lanes, ("forward", "backward"), strict=True)
    )


def _dc_width_m(
    tags: Mapping[str, str], dc_blocks: Sequence | None, rules: DcRules = DC_RULES
) -> float | None:
    """The narrowest District block's figure, or None where no block gives one."""
    if not dc_blocks or tags.get("highway") in DEFAULT_PATH_WIDTH_M:
        return None
    figures = [f for f in (_dc_block_width_m(block, rules) for block in dc_blocks) if f is not None]
    return min(figures) if figures else None


def usable_width_m(
    tags: Mapping[str, str],
    per_direction_lanes: int | None = None,
    dc_blocks: Sequence | None = None,
    rules: DcRules = DC_RULES,
) -> float | None:
    """The width a corked group has on the way in the direction it rides (the
    narrower direction of a two-way street), metres, or None where the way is not
    one a width can be read for (no `highway`, or a class with no default).

    `per_direction_lanes` is the classifier's through lanes a direction (read only
    where OSM tags no lanes); `dc_blocks` the District Roadway Block records
    (`agency_roads.RoadFacts`) the way lies along (`WayFacts.block_facts`), which
    decide it where they record lanes and a lane width (OWNER-DECISIONS 404 (3))."""
    if not tags.get("highway"):
        return None
    width = _dc_width_m(tags, dc_blocks, rules)
    if width is None:
        width = _osm_width_m(tags, per_direction_lanes)
    if width is None:
        return None
    return min(max(width, MIN_USABLE_WIDTH_M), MAX_USABLE_WIDTH_M)


def width_source(
    tags: Mapping[str, str], dc_blocks: Sequence | None = None, rules: DcRules = DC_RULES
) -> str:
    """Where `usable_width_m` takes a way's width from: "dc" (the Roadway Block) or
    "osm" (OpenStreetMap, or a class default)."""
    return "dc" if _dc_width_m(tags, dc_blocks, rules) is not None else "osm"


def usable_width_rounded(
    tags: Mapping[str, str],
    per_direction_lanes: int | None = None,
    dc_blocks: Sequence | None = None,
    rules: DcRules = DC_RULES,
) -> float | None:
    """`usable_width_m` to the centimetre: what the segment table stores."""
    width = usable_width_m(tags, per_direction_lanes, dc_blocks, rules)
    return None if width is None else round(width, 2)


def capacity_rpm(
    tags: Mapping[str, str],
    per_direction_lanes: int | None = None,
    dc_blocks: Sequence | None = None,
    rules: DcRules = DC_RULES,
) -> int | None:
    """Riders a minute the way carries, flat and straight, or None if unknown."""
    width = usable_width_m(tags, per_direction_lanes, dc_blocks, rules)
    return None if width is None else round(flow.level_riders_per_min(width))


# The Mass Ride bands, riders a minute (OWNER-DECISIONS 326, 327): the lower
# bound of each, in order. The front end holds its own copy
# (`frontend/src/lib/massCapacity.ts`), which a test holds equal.
BAND_FLOORS = (0, *flow.BAND_EDGES)
BAND_NAMES = flow.BAND_WORDS


def band_of(rpm: float) -> int:
    """The band, 0 (under 60) to 3 (200 and up), of a riders-a-minute figure."""
    return flow.band_index(rpm)
