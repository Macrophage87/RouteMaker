"""What kind of bicycle facility a way is, in the owner's four classes.

The owner, 2026-09-27: "Also, show and perfer protected bike lanes and off road
bike paths. They should get a bump for routing: Basically the preference goes
here: Off-road bike lanes > Protected Bike Lanes >> Marked Bike Lanes >
Ordinary Streets. Sharrows don't count as anything." And earlier the same day:
"We might also want a separate category for traffic free paths." And: "There
are a couple roads like beach drive in Montgomery County that are closed to car
traffic on the weekends. These should be considered off road paths then. (most
of beach drive in DC is closed to car traffic permanantly)"

So there are four classes, and "traffic-free path" is the first of them:

- `path`: a trail-class way a bicycle may ride that runs away from motor
  traffic, and a road closed to motor vehicles outright (the car-free parts of
  Beach Drive in DC, the Capitol grounds drives, Pyrite Mine Road). A road
  closed only at set times is the road it is otherwise, and counts as a path
  only for a ride inside the closure (`car_free_when`, read at request time).
- `protected`: a cycle track on the roadway (`cycleway*=track`), a painted
  lane with a physical separation tagged (`cycleway*:separation=flex_post`,
  `kerb`, ...), and a trail-class way that is the separately mapped facility
  beside a road: tagged as a sidewalk designated for bicycles, `is_sidepath`,
  a physical `separation*` from the road, or lying along a road that says its
  facility is mapped `separate` (`beside_separate_road`, found by geometry at
  the rebuild). DC maps most of its protected lanes that last way.
- `lane`: a painted lane (`lane`, `opposite_lane`, `buffered_lane`); a
  painted buffer is still paint.
- `none`: everything else, sharrows (`shared_lane`) and bus lanes shared with
  buses included, sidewalks a bicycle may merely use, and any way a bicycle may
  not ride.

A road's cycleway is read the way the stress classifier reads it
(`tags.cycleway_provision`): the worst direction a rider may be made to use, so
a one-sided lane on a two-way street is no facility for the other direction and
the way is scored as the weaker.

This is the single source of truth: the rebuild writes it onto
`segment.facility`, which the route breakdown and the facility tiles read, and
hands it to the tag transform (`rm:facility`), which is where routing is made
to prefer it.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from enum import StrEnum

from .classes import MOTOR_ONLY_HIGHWAY, TRAIL_CLASS_HIGHWAY
from .ridetime import closed_settings
from .tags import CYCLEWAY_KEYS, cycleway_provision


class Facility(StrEnum):
    PATH = "path"
    PROTECTED = "protected"
    LANE = "lane"
    NONE = "none"


FACILITIES = tuple(f.value for f in Facility)

# `bicycle` values that let a bicycle ride a way whose class does not by default.
BICYCLE_ALLOWED = frozenset({"yes", "designated", "permissive", "official"})

# The trail classes Valhalla's own transform opens to a bicycle with no bicycle
# tag (upstream graph.lua's highway table, `bike_forward = "true"`).
TRAIL_OPEN_BY_DEFAULT = frozenset({"cycleway", "path"})

# Values of the access keys that say no more than "the public may use it".
_PERMISSIVE_ACCESS = frozenset({"yes", "permissive", "designated", "official", "public"})

# Physical separation between a lane and the traffic beside it. Paint of any
# kind (`buffer`, `solid_line`, `dashed_line`) is not in it.
PHYSICAL_SEPARATION = frozenset(
    {
        "flex_post",
        "bollard",
        "kerb",
        "planter",
        "jersey_barrier",
        "concrete_barrier",
        "fence",
        "guard_rail",
        "parking_lane",
        "vertical_panel",
        "hedge",
        "tree_row",
        "yes",
    }
)
SEPARATION_KEYS = (
    "cycleway:left:separation",
    "cycleway:right:separation",
    "cycleway:both:separation",
    "cycleway:separation",
)
TRAIL_SEPARATION_KEYS = ("separation", "separation:left", "separation:right", "separation:both")

SIDEWALK = "sidewalk"
# Trail-class ways that cross a road rather than leave it: a marked crossing,
# or the refuge in the middle of one. They are part of the street they cross,
# not an off-road path (PUBLIC-TILES review, 2026-09-28: 3,328 footway=crossing
# and 233 footway=traffic_island ways in the region open to bicycles were
# counted as paths) - with one exception: a crossing signed for bicycles
# (`bicycle=designated`) carries a trail across the road, and stays the
# trail's, as `highway=cycleway` + `cycleway=crossing` does (correctness
# review, 2026-09-28). An island is never the trail's.
CROSSING_KEYS = ("footway", "path", "cycleway")
CROSSING = "crossing"
TRAFFIC_ISLAND = "traffic_island"

# The keys that close a road to motor traffic, outright or at set times.
MOTOR_KEYS = ("motor_vehicle", "motorcar")


def _physical(value: str | None) -> bool:
    return bool(value) and any(part.strip() in PHYSICAL_SEPARATION for part in value.split(";"))


def _unrestricted(tags: dict[str, str], keys: Sequence[str]) -> bool:
    return all(tags.get(key) is None or tags[key] in _PERMISSIVE_ACCESS for key in keys)


def trail_open_to_bicycle(tags: dict[str, str]) -> bool:
    """Whether a bicycle may ride a trail-class way, as Valhalla will read it."""
    bicycle = tags.get("bicycle")
    if bicycle is not None:
        return bicycle in BICYCLE_ALLOWED
    return tags.get("highway") in TRAIL_OPEN_BY_DEFAULT and _unrestricted(
        tags, ("access", "vehicle")
    )


def closed_to_motor_traffic(tags: dict[str, str]) -> bool:
    """A road whose tags close it to motor vehicles for good, and open it to bicycles."""
    bicycle = tags.get("bicycle")
    explicitly_open = bicycle in BICYCLE_ALLOWED
    if bicycle is not None and not explicitly_open:
        return False
    if any(tags.get(key) == "no" for key in MOTOR_KEYS):
        # `motor_vehicle=no` says nothing about bicycles; the way must still be
        # open to them, by its own tag or by nothing barring it.
        return explicitly_open or _unrestricted(tags, ("access", "vehicle"))
    # `access=no` or `vehicle=no` bar bicycles too, unless the bicycle tag
    # reopens the way; then the way is closed to everything else.
    return explicitly_open and (tags.get("access") == "no" or tags.get("vehicle") == "no")


def car_free_when(tags: dict[str, str]) -> frozenset[str]:
    """The ride-time settings in which a road is closed to motor traffic by a condition."""
    highway = tags.get("highway")
    if highway in TRAIL_CLASS_HIGHWAY or highway in MOTOR_ONLY_HIGHWAY or highway is None:
        return frozenset()
    if tags.get("bicycle") is not None and tags["bicycle"] not in BICYCLE_ALLOWED:
        return frozenset()
    closed: frozenset[str] = frozenset()
    for key in MOTOR_KEYS:
        closed |= closed_settings(tags.get(f"{key}:conditional"))
    return closed


def facility(tags: dict[str, str], beside_separate_road: bool = False) -> Facility:
    """The way's facility class."""
    highway = tags.get("highway")
    if highway in TRAIL_CLASS_HIGHWAY:
        if highway == "steps" or not trail_open_to_bicycle(tags):
            return Facility.NONE
        kinds = {tags.get(key) for key in CROSSING_KEYS}
        if TRAFFIC_ISLAND in kinds:
            return Facility.NONE
        if CROSSING in kinds and highway != "cycleway" and tags.get("bicycle") != "designated":
            return Facility.NONE
        if SIDEWALK in (tags.get("footway"), tags.get("path"), tags.get("cycleway")):
            # A signed sidepath is the protected facility beside its road; a
            # sidewalk a bicycle may merely use is not a facility at all.
            return Facility.PROTECTED if tags.get("bicycle") == "designated" else Facility.NONE
        if (
            beside_separate_road
            or tags.get("is_sidepath") == "yes"
            or any(_physical(tags.get(key)) for key in TRAIL_SEPARATION_KEYS)
        ):
            return Facility.PROTECTED
        return Facility.PATH
    if highway is None or highway in MOTOR_ONLY_HIGHWAY:
        return Facility.NONE
    if closed_to_motor_traffic(tags):
        return Facility.PATH
    provision = cycleway_provision(tags)
    if provision.rank >= 2:
        return Facility.PROTECTED
    if provision.rank == 1:
        if any(_physical(tags.get(key)) for key in SEPARATION_KEYS):
            return Facility.PROTECTED
        return Facility.LANE
    return Facility.NONE


# --- Separately mapped protected lanes ----------------------------------------

# How close a trail-class way has to run to a road that says its facility is
# mapped `separate` to be that facility, and for how much of its length. DC's
# separately mapped lanes sit 3-12 m from the road's centreline; 20 m keeps a
# trail on the far side of a wide boulevard out.
BESIDE_M = 20.0
BESIDE_FRACTION = 0.6

_EARTH_M = 6_371_008.8


def declares_separate(tags: dict[str, str]) -> bool:
    return any(tags.get(key) == "separate" for key in CYCLEWAY_KEYS)


def _xy(lon: float, lat: float, lat0: float) -> tuple[float, float]:
    return (
        math.radians(lon) * _EARTH_M * math.cos(math.radians(lat0)),
        math.radians(lat) * _EARTH_M,
    )


def _point_segment_m(p, a, b) -> float:
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def beside_separate_roads(
    ways: Iterable[tuple[int, dict[str, str], Sequence[tuple[float, float]]]],
) -> set[int]:
    """The trail-class ways lying along a road that declares `cycleway*=separate`.

    `ways` is (osm id, tags, [(lon, lat), ...]). A trail-class way is beside
    such a road when at least `BESIDE_FRACTION` of its vertices are within
    `BESIDE_M` of one. Only the ways that would otherwise be a `path` are asked.
    """
    ways = list(ways)
    if not ways:
        return set()
    lat0 = 38.9
    cell = BESIDE_M
    grid: dict[tuple[int, int], list[tuple[tuple[float, float], tuple[float, float]]]] = {}
    for _, tags, coords in ways:
        if tags.get("highway") in TRAIL_CLASS_HIGHWAY or not declares_separate(tags):
            continue
        points = [_xy(lon, lat, lat0) for lon, lat in coords]
        for a, b in zip(points, points[1:], strict=False):
            x0, x1 = sorted((a[0], b[0]))
            y0, y1 = sorted((a[1], b[1]))
            for gx in range(int(x0 // cell) - 1, int(x1 // cell) + 2):
                for gy in range(int(y0 // cell) - 1, int(y1 // cell) + 2):
                    grid.setdefault((gx, gy), []).append((a, b))
    if not grid:
        return set()
    found = set()
    for osm_id, tags, coords in ways:
        if tags.get("highway") not in TRAIL_CLASS_HIGHWAY or len(coords) < 2:
            continue
        if facility(tags) is not Facility.PATH:
            continue
        points = [_xy(lon, lat, lat0) for lon, lat in coords]
        near = 0
        for p in points:
            candidates = grid.get((int(p[0] // cell), int(p[1] // cell)), ())
            if any(_point_segment_m(p, a, b) <= BESIDE_M for a, b in candidates):
                near += 1
        if near >= BESIDE_FRACTION * len(points):
            found.add(osm_id)
    return found
