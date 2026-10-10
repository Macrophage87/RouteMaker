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
from .tags import CYCLEWAY_KEYS, PERMISSIVE_ACCESS, cycleway_provision, narrow_access_lists


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


def physically_closed(tags: dict[str, str]) -> bool:
    """A way mapped as impassable, which the router closes to every vehicle
    (`impassable=yes`; `smoothness=impassable` from Valhalla 3.6.0) unless a
    bicycle tag reopens it (lua/routemaker_remap.lua, `physically_closed`)."""
    return tags.get("impassable") == "yes" or tags.get("smoothness") == "impassable"


def _public_vehicle_grant(tags: dict[str, str]) -> bool:
    vehicle = tags.get("vehicle")
    return vehicle is not None and all(
        part.strip() in PERMISSIVE_ACCESS for part in vehicle.split(";")
    )


# The `vehicle` values Valhalla 3.6.2 reads as a grant, and the `access` values
# whose closure such a grant does not lift for a bicycle (lua/routemaker_remap.lua,
# `VEHICLE_GRANTS` and `ACCESS_CLOSES`; `trailaccess.UPSTREAM_VEHICLE_ACCESS`).
VEHICLE_GRANTS = frozenset(
    {
        "yes", "private", "permissive", "delivery", "designated", "destination", "customers",
        "official", "public", "restricted", "allowed", "permit", "residents",
    }
)  # fmt: skip
ACCESS_CLOSES = frozenset({"no", "agricultural", "forestry", "discouraged", "emergency", "psv"})


def _restricted_vehicle_grant_on_open_class(tags: dict[str, str]) -> bool:
    """A cycleway or path with a restricted `vehicle` grant (`vehicle=delivery`)
    and no closing `access`: upstream opens it, and the remap leaves it open
    because the class is open to bicycles anyway (`vehicle_reopens_for_bicycle`)."""
    vehicle = tags.get("vehicle")
    return (
        vehicle is not None
        and tags.get("highway") in TRAIL_OPEN_BY_DEFAULT
        and tags.get("access") not in ACCESS_CLOSES
        and any(part.strip() in VEHICLE_GRANTS for part in vehicle.split(";"))
    )


def trail_open_to_bicycle(tags: dict[str, str]) -> bool:
    """Whether a bicycle may ride a trail-class way, as Valhalla will read it:
    access lists narrowed as the transform narrows them, a bicycle tag first,
    then impassability, then a public `vehicle` grant (read for bicycles from
    Valhalla 3.6.2, valhalla/valhalla#5802), then the class default."""
    tags = narrow_access_lists(tags)
    bicycle = tags.get("bicycle")
    if bicycle is not None:
        return any(part.strip() in BICYCLE_ALLOWED for part in bicycle.split(";"))
    if physically_closed(tags):
        return False
    if _public_vehicle_grant(tags) or _restricted_vehicle_grant_on_open_class(tags):
        return True
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


# What a trail's own tags say about lying beside a road (OWNER-DECISIONS 403: "Most trails
# near a road are paved."): a sidewalk (`footway`, `path` or `cycleway` = sidewalk, whatever
# the bicycle access), `is_sidepath=yes`, or any `is_sidepath:of*` naming the road.
SIDEPATH_OF_PREFIX = "is_sidepath:of"


def roadside_by_tags(tags: dict[str, str]) -> bool | None:
    """True where a trail's tags say it is a sidepath beside a road, False where they say
    it is not (`is_sidepath=no`, which the geometry does not overrule), None where they do
    not say (the rebuild then asks the geometry: `pipeline.trail_routes.derive_roadside`)."""
    sidepath = tags.get("is_sidepath")
    if sidepath == "no":
        return False
    if sidepath == "yes":
        return True
    if SIDEWALK in (tags.get("footway"), tags.get("path"), tags.get("cycleway")):
        return True
    if any(key.startswith(SIDEPATH_OF_PREFIX) for key in tags):
        return True
    return None


def roadside_start(tags: dict[str, str], facility_class: str, *, drawn_trail: bool) -> bool | None:
    """The `segment.roadside` the rebuild writes before the geometry is asked: False on a
    way that is not a trail the map draws, the tags' answer where they give one, True on a
    trail already classed the protected facility beside a road, and None (ask the
    geometry) otherwise."""
    if not drawn_trail:
        return False
    by_tags = roadside_by_tags(tags)
    if by_tags is not None:
        return by_tags
    if facility_class == Facility.PROTECTED.value:
        return True
    return None


def declares_separate(tags: dict[str, str]) -> bool:
    return any(tags.get(key) == "separate" for key in CYCLEWAY_KEYS)


class MapClass(StrEnum):
    """How the stress map draws a way, beside its tier (OWNER-DECISIONS 73, 80,
    82, 88, 89). Only a road is drawn; the other two are kept apart for what
    they mean, not for how they draw."""

    ROAD = "road"
    # A public road a bicycle may not use - a motorway, bicycle=no,
    # motorroad=yes: not drawn, the base map shows it as it is ("You can just
    # leave the public roads where bikes aren't allowed as unmarked, using the
    # base map", 89, superseding the white line of 73 and 80).
    BARRED = "barred"
    # No road or path a typical rider could use: a terminal hallway, a
    # sidewalk, a parking aisle, a private road, a road inside a military base
    # (80, 82, 88). Not drawn.
    HIDDEN = "hidden"
    # An alley (`service=alley`): drawn only close in, faint, as context. The
    # owner, 2026-09-29: "Alley cut throughs should only be used if the roads
    # are very problematic nearby. Cut down on showing them, and only use them
    # if nessicary. Because people don't think of these as intersections, alley
    # dodging is dangerous." (OWNER-DECISIONS 100). From the source tags: the
    # tier-5 roads the transform marks service=alley in Valhalla's extract are
    # not alleys here.
    ALLEY = "alley"


# Ways that are not roads or paths a bicycle could use, whatever their tags:
# an airport terminal's hallways (BWI, `highway=corridor` + `indoor=yes`,
# rated "mixed traffic, 30 mph" and drawn LTS 3 - the owner, 2026-09-29: "For
# some strange reason BWI has TLS 3 inside the terminal."; OWNER-DECISIONS
# 80), a lift, a platform, a road not built yet. Valhalla's transform does not
# route them either (lua/graph.lua: corridor is bike_forward = false).
NOT_A_WAY_HIGHWAY = frozenset(
    {
        "corridor",
        "elevator",
        "platform",
        "bus_stop",
        "proposed",
        "construction",
        "raceway",
        "escape",
    }
)

# A motorway and its ramps bar bicycles unless a bicycle tag opens them.
BARRED_HIGHWAY = frozenset({"motorway", "motorway_link"})

# A bicycle tag that keeps a bicycle off the roadway: barred, private, or sent
# to the sidepath beside it.
BARRING_BICYCLE = frozenset({"no", "private", "use_sidepath"})

# Access values that keep the public out, a bicycle included, unless the
# bicycle tag says otherwise: the road is no one's to ride, and is left off the
# map (the owner, 2026-09-29: "Don't show roads that most typical people can't
# ride on, such as within military bases, or the pentagon"; OWNER-DECISIONS
# 88). `permit` is taken as private-like: a gate and a pass.
NO_PUBLIC_ACCESS = frozenset({"no", "private", "military", "restricted", "permit"})

# A way's own tags that open it to someone on foot or on a bicycle.
PUBLIC_WAY = frozenset({"yes", "designated", "permissive", "official", "public"})


# The service roads a map of where to ride has no use for (the owner,
# 2026-09-29: "There's a lot of side paths and parking lots that probably
# don't need to show up." - "Sidewalks + small paths"; OWNER-DECISIONS 82).
HIDDEN_SERVICE = frozenset({"parking_aisle", "driveway", "drive-through"})

# How short an unnamed footway or path has to be for the map to leave it out
# (82), unless it joins two trails the map keeps (`short_paths_to_hide`).
SHORT_PATH_M = 150.0


def _sidewalk_or_crossing(tags: dict[str, str]) -> bool:
    """A sidewalk, or a crosswalk's line across a road, that is not a trail: a
    sidewalk designated for bicycles is a roadside trail (OWNER-DECISIONS 66),
    and a crossing signed for bicycles, or a cycleway's own, carries its trail
    across the road (the facility rule's CROSSING_KEYS)."""
    kinds = {tags.get(key) for key in CROSSING_KEYS}
    if tags.get("bicycle") == "designated":
        return False
    # A stretch of a named trail mapped as the sidewalk it runs along (the
    # Anacostia Riverwalk Trail's, footway=sidewalk + bicycle=yes) is the
    # trail's: a named trail stays on the map (OWNER-DECISIONS 82).
    if tags.get("name") and tags.get("bicycle") in BICYCLE_ALLOWED:
        return False
    # A sidewalk open to bicycles that carries a segregated tag is a shared-use
    # sidepath someone mapped with care, not a plain sidewalk: it stays (the
    # owner, 2026-09-30: "Keep tagged sidepaths"; OWNER-DECISIONS 115, after the
    # Veirs Mill Road sidepath was found hidden). 551 such ways in the source
    # extract of 2026-09-24.
    if tags.get("bicycle") in BICYCLE_ALLOWED and tags.get("segregated") is not None:
        return False
    if SIDEWALK in kinds:
        return True
    return bool(kinds & {CROSSING, TRAFFIC_ISLAND}) and tags.get("highway") != "cycleway"


def short_path_candidate(tags: dict[str, str]) -> bool:
    """An unnamed footway or path not designated for bicycles: left out of the
    map when it is short and joins no two kept trails (`short_paths_to_hide`)."""
    return (
        tags.get("highway") in ("footway", "path")
        and not tags.get("name")
        and tags.get("bicycle") != "designated"
    )


# `bicycle_road=yes` / `cyclestreet=yes`: a road signed for bicycles, which
# Valhalla's transform opens to them whatever the class (`pipeline.run`'s
# `_OPENS_OVER_BICYCLE_NO`). OWNER-DECISIONS 442: the car-free piece of Beach
# Drive (way 24976160, `highway=pedestrian`, `bicycle_road=yes`, no bicycle tag)
# stayed routable but dropped off the stress map.
BICYCLE_ROAD_KEYS = ("bicycle_road", "cyclestreet")


def is_bicycle_road(tags: dict[str, str]) -> bool:
    """A way signed as a bicycle road, with no bicycle tag that says otherwise.

    For the map only: what is drawn as open, never what routing opens.
    """
    if tags.get("bicycle") is not None:
        return False
    return any(tags.get(key) == "yes" for key in BICYCLE_ROAD_KEYS)


def map_class(tags: dict[str, str]) -> MapClass:
    """How the stress map draws a way, by its own tags; a road inside a
    military base is found by its place (`pipeline.military`). BARRED: a
    public road a bicycle may not use - a motorway, `bicycle=no` (the George
    Washington, Suitland and Clara Barton parkways), `motorroad=yes`,
    `bicycle=use_sidepath`. HIDDEN: a way no typical rider could use - no road
    or path at all (a terminal hallway, `indoor`), a sidewalk or crosswalk, a
    parking aisle or driveway, and a road or path the public may not enter
    (`access` or `vehicle` of no, private, military, restricted, permit), a
    bicycle or foot tag reopening it. Neither is drawn (OWNER-DECISIONS 89).
    "Legal but avoid" (US 340) is a road a bicycle may use, and keeps its
    tier."""
    highway = tags.get("highway")
    if highway in NOT_A_WAY_HIGHWAY or tags.get("indoor", "no") != "no":
        return MapClass.HIDDEN
    if highway == "service" and tags.get("service") in HIDDEN_SERVICE:
        return MapClass.HIDDEN
    closed = any(tags.get(key) in NO_PUBLIC_ACCESS for key in ("access", "vehicle"))
    if highway in TRAIL_CLASS_HIGHWAY:
        if _sidewalk_or_crossing(tags):
            return MapClass.HIDDEN
        # A private path (inside the Pentagon's fence) is no one's; a public
        # one is a trail, whatever its facility.
        opened = tags.get("bicycle") in PUBLIC_WAY or tags.get("foot") in PUBLIC_WAY
        if closed and not opened:
            return MapClass.HIDDEN
        # A trail a bicycle may not ride (a footway with no bicycle tag, a path
        # tagged `bicycle=no`, steps) is not drawn as a bike path: it is left
        # to the base map like a road a bicycle may not use (OWNER-DECISIONS
        # 278, 290(b)). A short `bicycle=dismount` connector stays: routing
        # keeps it, and the route says to walk.
        if (
            tags.get("bicycle") != "dismount"
            and not trail_open_to_bicycle(tags)
            and not is_bicycle_road(tags)
        ):
            return MapClass.BARRED
        return MapClass.ROAD
    if highway is None:
        return MapClass.ROAD
    bicycle = tags.get("bicycle")
    alley = highway == "service" and tags.get("service") == "alley"
    if bicycle in BICYCLE_ALLOWED:
        # An alley open to bicycles is still an alley: routing prices it like
        # an LTS 3 street whatever its bicycle tag (lua/routemaker_remap.lua,
        # `is_real_alley`), so the map keeps it close in and faint as well.
        return MapClass.ALLEY if alley else MapClass.ROAD
    if closed or bicycle == "private":
        return MapClass.HIDDEN
    if (
        highway in BARRED_HIGHWAY
        or bicycle in BARRING_BICYCLE
        or tags.get("motorroad") == "yes"
        or (bicycle is None and physically_closed(tags))
    ):
        return MapClass.BARRED
    if alley:
        return MapClass.ALLEY
    return MapClass.ROAD


def bike_access_reason(
    tags: dict[str, str],
    *,
    no_bicycle: str | None = None,
    overridden: bool = False,
) -> str | None:
    """Why a bicycle may not use a way, or why it was reopened, as one short code
    for the map's road panel (`segment.bike_access_reason`; OWNER-DECISIONS 441a;
    `core.segment_info.ACCESS_WORDS` words it). None on a way with nothing to say.

    `no_bicycle` is the way's `rm:no_bicycle` reason (military, secured, a trail
    rule, the CBD sidewalks; `pipeline.trail_closures`), `overridden` whether an
    approved access override wrote a bicycle key on it. An override is named
    first, closed or open by the tag it left, unless a closure rule still closed
    the way; then the rule's reason, then what the way's own tags say. Whether the
    graph lets a bicycle on the way is the router's to say: this is only the why.
    """
    bicycle = tags.get("bicycle")
    if overridden and no_bicycle is None:
        if bicycle in BICYCLE_ALLOWED or bicycle == "dismount":
            return "override_open"
        if bicycle in BARRING_BICYCLE:
            return "override_closed"
    if no_bicycle is not None:
        return no_bicycle
    if bicycle in BICYCLE_ALLOWED:
        return None
    if bicycle == "no":
        return "bicycle_no"
    if bicycle == "use_sidepath":
        return "bicycle_use_sidepath"
    if bicycle == "private" or any(tags.get(k) in NO_PUBLIC_ACCESS for k in ("access", "vehicle")):
        return "private"
    if bicycle is None and physically_closed(tags):
        return "impassable"
    if tags.get("highway") in BARRED_HIGHWAY:
        return "motorway"
    if tags.get("motorroad") == "yes":
        return "motorroad"
    return None


def has_separate_bikeway(tags: dict[str, str]) -> bool:
    """Whether a road says its bike facility is mapped as a way of its own
    beside it (`cycleway*=separate`): 15th Street NW and Pennsylvania Avenue NW
    beside their cycle tracks. The stress map draws such a road faint and only
    from close in, so the facility beside it is the main line (the owner,
    2026-09-29: "there's several cases of a protected bike lane next to LTS3
    or 4. In that case, don't show the road, perhaps hide it until zoom 15-16.
    The bike lane should show up as the main." and "Keep it faint if it
    parallels a protected bike path."; OWNER-DECISIONS 73, 78). A trail-class
    way is the facility, not the road."""
    return tags.get("highway") not in TRAIL_CLASS_HIGHWAY and declares_separate(tags)


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
    return separate_pairs(ways)[0]


def separate_pairs(
    ways: Iterable[tuple[int, dict[str, str], Sequence[tuple[float, float]]]],
) -> tuple[set[int], set[int]]:
    """(the trails `beside_separate_roads` finds, the roads they lie beside).

    The second set is what the arterial floor (OWNER-DECISIONS 141) reads as
    "bike infrastructure": a road that says its facility is mapped separately
    and has such a trail along it.
    """
    ways = list(ways)
    if not ways:
        return set(), set()
    lat0 = 38.9
    cell = BESIDE_M
    grid: dict[tuple[int, int], list[tuple[tuple[float, float], tuple[float, float], int]]] = {}
    for road_id, tags, coords in ways:
        if tags.get("highway") in TRAIL_CLASS_HIGHWAY or not declares_separate(tags):
            continue
        points = [_xy(lon, lat, lat0) for lon, lat in coords]
        for a, b in zip(points, points[1:], strict=False):
            x0, x1 = sorted((a[0], b[0]))
            y0, y1 = sorted((a[1], b[1]))
            for gx in range(int(x0 // cell) - 1, int(x1 // cell) + 2):
                for gy in range(int(y0 // cell) - 1, int(y1 // cell) + 2):
                    grid.setdefault((gx, gy), []).append((a, b, road_id))
    if not grid:
        return set(), set()
    found: set[int] = set()
    roads: set[int] = set()
    for osm_id, tags, coords in ways:
        if tags.get("highway") not in TRAIL_CLASS_HIGHWAY or len(coords) < 2:
            continue
        if facility(tags) is not Facility.PATH:
            continue
        points = [_xy(lon, lat, lat0) for lon, lat in coords]
        near = 0
        beside: set[int] = set()
        for p in points:
            candidates = grid.get((int(p[0] // cell), int(p[1] // cell)), ())
            hits = {road for a, b, road in candidates if _point_segment_m(p, a, b) <= BESIDE_M}
            if hits:
                near += 1
                beside |= hits
        if near >= BESIDE_FRACTION * len(points):
            found.add(osm_id)
            roads |= beside
    return found, roads


def _length_m(coords: Sequence[tuple[float, float]]) -> float:
    if len(coords) < 2:
        return 0.0
    lat0 = coords[0][1]
    points = [_xy(lon, lat, lat0) for lon, lat in coords]
    return sum(math.dist(a, b) for a, b in zip(points, points[1:], strict=False))


def short_paths_to_hide(
    ways: Iterable[tuple[int, dict[str, str], Sequence[int], Sequence[tuple[float, float]]]],
    max_m: float = SHORT_PATH_M,
) -> set[int]:
    """The short unnamed footways and paths the map leaves out (OWNER-DECISIONS
    82): a `short_path_candidate` shorter than `max_m`, unless both its ends
    touch a trail-class way the map keeps - a short link between two trails
    stays, so the trails do not look broken where it joins them.

    `ways` is (osm id, tags, node ids, [(lon, lat), ...]). A kept trail is a
    trail-class way that is not a candidate and that `map_class` draws (a named
    trail, a long path, a shared-use path, a roadside trail).
    """
    ways = list(ways)
    short: dict[int, tuple[int, int]] = {}
    kept_nodes: set[int] = set()
    for osm_id, tags, node_ids, coords in ways:
        if tags.get("highway") not in TRAIL_CLASS_HIGHWAY or not node_ids:
            continue
        if map_class(tags) is not MapClass.ROAD:
            continue
        if short_path_candidate(tags) and _length_m(coords) < max_m:
            short[osm_id] = (node_ids[0], node_ids[-1])
        else:
            kept_nodes.update(node_ids)
    return {
        osm_id
        for osm_id, (first, last) in short.items()
        if not (first in kept_nodes and last in kept_nodes)
    }
