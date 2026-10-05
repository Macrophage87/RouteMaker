"""How many riders a road carries per minute: the Mass Ride capacity (PLAN.md,
"The headline number: modelled throughput").

The owner, 2026-10-04: "The focus is on carrying capacity, not LTS here. ...
The headline color should be riders per minute." (OWNER-DECISIONS 325), in
riders per minute at 6-8 mph (326), with the bands 60, 120 and 200 (327).

The model is the plan's, calibrated to the owner's counts of three DC Bike
Party rides (item 173, `reports/owner/cyclist_packing_density.md`):

    riders a minute = 60 x safe density x utilisation x usable width x pace

- safe density 0.37 riders per square metre: the measured packing at a pinch,
  turn or signal queue, which is the state a road is judged by ("a ride flows at
  its narrowest point");
- utilisation 0.7: a pack bunches toward part of the road rather than filling it;
- pace 1.9 m/s (4.3 mph): the pace that density was measured at. The flow is
  conserved through a slowdown, so at the 6-8 mph cruise the same riders pass
  each second over more road (looser), and the headline stays this figure.

That is 29.5 riders a minute for every metre of usable width: about 99 per 11 ft
(3.35 m) lane, 198 on a 22 ft two-lane street. The constants are the plan's, and
every one is owner-confirmable (they are named here once so the front end's
bands need no second copy).

Usable width comes from the tags (`usable_width_m`): the carriageway's own
`width` where mapped; otherwise the travel lanes times a lane width, plus a
painted bike lane on the roadway (a protected lane is not usable, OWNER-
DECISIONS item 127), with a highway-class default where the lanes are not
tagged. Parking lanes are not added: parked cars are in them, and a pack cannot
count on the space (a proposal for the owner to confirm; PLAN.md). Grade,
surface and turns are reductions the route applies (part 2); this is the flat,
straight, clear-road figure, which is what the map is coloured by.

The figure is the LEVEL capacity only (`flow.level_riders_per_min`): the grade
adjustment depends on direction and distance into a climb, so the route chart
applies it (`flow.adjusted_riders_per_min`), not the map tiles.

Pure functions of a way's tags: the rebuild writes the answer onto
`segment.mass_usable_width_m` (`pipeline.run`), and nothing reads the tags again.
"""

from __future__ import annotations

from collections.abc import Mapping

from . import flow
from .tags import PAINTED_CYCLEWAY, cycleway_sides, is_oneway, parse_int, parse_width_m

# The calibrated constants are `routemaker.flow`'s (copied verbatim from the
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
# A way that is a path, not a street: its width where none is mapped.
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


def _lanes_total(tags: Mapping[str, str], per_direction: int | None, oneway: bool) -> int | None:
    """Travel lanes across the roadway, both directions, from the tags, else the
    classifier's through lanes a direction, else None (the class default)."""
    directional = [parse_int(tags.get(key)) for key in ("lanes:forward", "lanes:backward")]
    known = [lanes for lanes in directional if lanes is not None]
    if known and len(known) == 2:
        return max(1, sum(known))
    total = parse_int(tags.get("lanes"))
    if total is not None and total >= 1:
        return total
    if per_direction is not None and per_direction >= 1:
        return per_direction if oneway else 2 * per_direction
    return None


def usable_width_m(tags: Mapping[str, str], per_direction_lanes: int | None = None) -> float | None:
    """The width a pack can use, in metres, or None where the way is not one a
    width can be read for (no `highway`)."""
    highway = tags.get("highway")
    if not highway:
        return None
    mapped = parse_width_m(tags.get("width"))
    if mapped is not None and MIN_MAPPED_WIDTH_M <= mapped <= MAX_MAPPED_WIDTH_M:
        return min(max(mapped, MIN_USABLE_WIDTH_M), MAX_USABLE_WIDTH_M)
    if highway in DEFAULT_PATH_WIDTH_M:
        return DEFAULT_PATH_WIDTH_M[highway]
    oneway = is_oneway(tags)
    tagged_total = _lanes_total(tags, None, oneway)
    lanes = _lanes_total(tags, per_direction_lanes, oneway)
    if lanes is None:
        default = DEFAULT_LANES.get(highway)
        if default is None:
            return None
        lanes = max(1, default // 2) if oneway and default > 1 else default
    if tagged_total is None and per_direction_lanes and per_direction_lanes >= 1:
        # The classifier's lanes a direction: the elevation chart's own width
        # (`flow.usable_width_m`), so the chart and the map agree.
        width = flow.usable_width_m("1", "none", per_direction_lanes, oneway)
    else:
        width = lanes * LANE_WIDTH_M
    # A painted lane on the roadway is usable; a protected one is not (127), and a
    # side that says it has none has none (`cycleway_sides` reads the precedence).
    for side in cycleway_sides(dict(tags)).values():
        if side.value in PAINTED_CYCLEWAY:
            width += side.width_m if side.width_m else PAINTED_LANE_DEFAULT_M
    return min(max(width, MIN_USABLE_WIDTH_M), MAX_USABLE_WIDTH_M)


def usable_width_rounded(
    tags: Mapping[str, str], per_direction_lanes: int | None = None
) -> float | None:
    """`usable_width_m` to the centimetre: what the segment table stores."""
    width = usable_width_m(tags, per_direction_lanes)
    return None if width is None else round(width, 2)


def capacity_rpm(tags: Mapping[str, str], per_direction_lanes: int | None = None) -> int | None:
    """Riders a minute the way carries, flat and straight, or None if unknown."""
    width = usable_width_m(tags, per_direction_lanes)
    return None if width is None else round(flow.level_riders_per_min(width))


# The Mass Ride bands, riders a minute (OWNER-DECISIONS 326, 327): the lower
# bound of each, in order. The front end holds its own copy
# (`frontend/src/lib/massCapacity.ts`), which a test holds equal.
BAND_FLOORS = (0, *flow.BAND_EDGES)
BAND_NAMES = flow.BAND_WORDS


def band_of(rpm: float) -> int:
    """The band, 0 (under 60) to 3 (200 and up), of a riders-a-minute figure."""
    return flow.band_index(rpm)
