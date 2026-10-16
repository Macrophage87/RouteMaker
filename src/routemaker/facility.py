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
  the rebuild) unless the way is a trail named for itself (Rock Creek Trail
  beside Rock Creek and Potomac Parkway). DC maps most of its protected lanes
  that last way.
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
from .tags import (
    CYCLEWAY_KEYS,
    PERMISSIVE_ACCESS,
    best_direction_provision,
    cycleway_provision,
    is_oneway,
    narrow_access_lists,
    open_to_buses,
)


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
    """A road whose tags close it to motor vehicles for good, and open it to bicycles.
    Never one open to buses (`tags.open_to_buses`, FOLLOWUP-BUS-ROADS): they are
    motor traffic."""
    if open_to_buses(tags):
        return False
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
    # Buses keep running through a closure to cars (FOLLOWUP-BUS-ROADS).
    if open_to_buses(tags):
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
    return _road_facility(tags, cycleway_provision(tags))


def shown_facility(tags: dict[str, str], beside_separate_road: bool = False) -> Facility | None:
    """The class the map and the road panel show where it is not `facility`'s, else None
    (the review of 17f69082): the best direction's (`tags.best_direction_provision`), so
    a contraflow-only lane shows as a lane. Display only: the tier and the routing price
    (`rm:facility`, `lua/routemaker_remap.lua` `apply_facility`) stay on `facility`, the
    rider with the traffic. Only on a one-way road: on a two-way road the weaker side is a
    rider's own direction, not a contraflow, so a lane on one side shows nothing new."""
    scored = facility(tags, beside_separate_road)
    highway = tags.get("highway")
    if (
        not is_oneway(tags)
        or highway is None
        or highway in TRAIL_CLASS_HIGHWAY
        or highway in MOTOR_ONLY_HIGHWAY
        or closed_to_motor_traffic(tags)
    ):
        return None
    shown = _road_facility(tags, best_direction_provision(tags))
    return shown if _RANK[shown] > _RANK[scored] else None


_RANK = {"none": 0, "lane": 1, "protected": 2, "path": 3}


def _road_facility(tags: dict[str, str], provision) -> Facility:
    """A road's class from one provision (`tags.Provision`)."""
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

# A bicycle tag that keeps a bicycle off the roadway: barred or private.
BARRING_BICYCLE = frozenset({"no", "private"})

# `bicycle=use_sidepath`: riders are asked to use the side path, but the roadway
# is still legal (the owner, 2026-10-16: "It's very much not recommended, but I
# believe still legal"; review RL-1), as Valhalla's transform reads it too. It
# is drawn and routed; where a side path is mapped beside it (`use_sidepath_paths`)
# it is rated Avoid, and where none is it is rated on its own merits and listed
# for review as a likely tagging error.
USE_SIDEPATH = "use_sidepath"

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
    Washington, Suitland and Clara Barton parkways), `motorroad=yes`.
    HIDDEN: a way no typical rider could use - no road
    or path at all (a terminal hallway, `indoor`), a sidewalk or crosswalk, a
    parking aisle or driveway, and a road or path the public may not enter
    (`access` or `vehicle` of no, private, military, restricted, permit), a
    bicycle or foot tag reopening it. Neither is drawn (OWNER-DECISIONS 89).
    "Legal but avoid" (US 340, `bicycle=use_sidepath`) is a road a bicycle may
    use, and keeps its tier."""
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
    side_path: bool = False,
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

    `side_path` says a side path is mapped beside a `bicycle=use_sidepath` road
    (`use_sidepath_paths`): the road is open, and the panel says riders are asked to
    use it. With none mapped the tag is read as a likely tagging error and says
    nothing here.
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
    if bicycle == "private" or any(tags.get(k) in NO_PUBLIC_ACCESS for k in ("access", "vehicle")):
        return "private"
    if bicycle is None and physically_closed(tags):
        return "impassable"
    if tags.get("highway") in BARRED_HIGHWAY:
        return "motorway"
    if tags.get("motorroad") == "yes":
        return "motorroad"
    # Last: `use_sidepath` never opens a way something above closes (review RL-1).
    if bicycle == USE_SIDEPATH and side_path:
        return "bicycle_use_sidepath"
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


# A named trail of its own is not the protected lane of the road it runs beside (the
# owner, 2026-10-12: "parts of rock creek trail are now marked as a protected bike
# lane rather than an off road trail, which it is"). Rock Creek Trail hugs Rock Creek
# and Potomac Parkway, which says `cycleway:left=separate` (OSM ways 435101942 and
# 1160956481), for most of its length between P Street and M Street NW, so the
# geometry alone made it the parkway's protected lane. A trail-class way keeps its
# path class when its own `name` is its own and not the road's: the road's facility is
# named for the road where it is named at all ("15th Street Northwest", "15th Street
# Cycletrack"), a trail is named for itself. Only the way's own name counts, never its
# route relation's: an unnamed DC cycle track on the East Coast Greenway or USBR 50
# (Pennsylvania Avenue's median lanes) is still the road's protected lane. A generic
# name ("Cycle Track", "Sidewalk", "Penn Ave Cycletrack") is never a trail's own. The
# road still counts as having its facility alongside (the arterial floor,
# OWNER-DECISIONS 141): the trail is that. A road's name is compared without a
# trailing quadrant or compass word and with street types spelled out, so a lane
# named "15th St NW" is still 15th Street Northwest's. Single letters are not
# stripped, so "Avenue N" stays itself.
_NAME_SUFFIXES = frozenset(
    {
        "northwest", "northeast", "southwest", "southeast", "nw", "ne", "sw", "se",
        "north", "south", "east", "west",
    }
)  # fmt: skip

# Names that say what a facility is, not which one it is: never a trail's own.
GENERIC_FACILITY_NAMES = frozenset(
    {
        "sidewalk", "cycle track", "cycletrack", "bike path", "bike lane", "bike lanes",
        "shared use path", "shared-use path", "sidepath", "side path", "trail",
    }
)  # fmt: skip
# And the endings that name a road's facility after the road ("Eye Street Cycle Track").
GENERIC_FACILITY_ENDINGS = (
    "sidepath", "side path", "cycle track", "cycletrack", "bike lane", "bike lanes",
)  # fmt: skip


# And with the usual street-type abbreviations spelled out ("15th St NW").
_STREET_TYPES = {
    "st": "street", "ave": "avenue", "av": "avenue", "rd": "road", "blvd": "boulevard",
    "dr": "drive", "pkwy": "parkway", "pky": "parkway", "pl": "place", "ter": "terrace",
    "ct": "court", "ln": "lane", "hwy": "highway", "cir": "circle", "sq": "square",
}  # fmt: skip


def _name_key(name: str | None) -> str:
    words = [
        _STREET_TYPES.get(word, word) for word in (name or "").lower().replace(".", " ").split()
    ]
    while words and words[-1] in _NAME_SUFFIXES:
        words.pop()
    return " ".join(words)


def generic_facility_name(name: str | None) -> bool:
    """A name that only says what kind of facility a way is (`GENERIC_FACILITY_NAMES`,
    `GENERIC_FACILITY_ENDINGS`)."""
    plain = " ".join((name or "").lower().replace(".", " ").split())
    return plain in GENERIC_FACILITY_NAMES or plain.endswith(GENERIC_FACILITY_ENDINGS)


def named_for_itself(trail_name: str | None, road_names: Iterable[str | None]) -> bool:
    """Whether a trail's name is its own rather than the road's beside it: it has a
    name, the name is not a generic one (`generic_facility_name`), and it does not
    begin with the name of any of those roads (each without a trailing quadrant). A
    road with no name never claims a named trail."""
    trail = _name_key(trail_name)
    if not trail or generic_facility_name(trail_name):
        return False
    for road_name in road_names:
        road = _name_key(road_name)
        if road and (trail == road or trail.startswith(road + " ")):
            return False
    return True


def beside_separate_roads(
    ways: Iterable[tuple[int, dict[str, str], Sequence[tuple[float, float]]]],
) -> set[int]:
    """The trail-class ways lying along a road that declares `cycleway*=separate`.

    `ways` is (osm id, tags, [(lon, lat), ...]). A trail-class way is beside
    such a road when at least `BESIDE_FRACTION` of its vertices are within
    `BESIDE_M` of one. Only the ways that would otherwise be a `path` are asked,
    and a trail whose own name is its own (`named_for_itself`) is never one.
    """
    return separate_pairs(ways)[0]


def separate_pairs(
    ways: Iterable[tuple[int, dict[str, str], Sequence[tuple[float, float]]]],
) -> tuple[set[int], set[int]]:
    """(the trails `beside_separate_roads` finds, the roads they lie beside).

    The second set is what the arterial floor (OWNER-DECISIONS 141) reads as
    "bike infrastructure": a road that says its facility is mapped separately
    and has such a trail along it. A named trail along it counts there too, though
    it stays a path in the first set.
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
    road_names = {
        road_id: tags.get("name")
        for road_id, tags, _coords in ways
        if tags.get("highway") not in TRAIL_CLASS_HIGHWAY and declares_separate(tags)
    }
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
            roads |= beside
            if not named_for_itself(tags.get("name"), (road_names.get(road) for road in beside)):
                found.add(osm_id)
    return found, roads


# --- An unnamed bike lane beside a named street (v0.7.0, "Go riding fixes" item 4) ------------

# The owner, 2026-10-15: "A protected bike lane was listed as an "unnamed path" near 9th
# and R NW." A cycleway or path with no name of its own that runs alongside a named street
# - within SIDE_STREET_M, roughly parallel (SIDE_STREET_ANGLE), for most of its length
# (SIDE_STREET_FRACTION) - is that street's bike lane: "9th Street Northwest bike lane",
# or "9th Street Northwest protected bike lane" where its tags say it is separated from
# the road (`separation*` physical) or segregated (`segregated=yes`). The rebuild writes
# the name onto `segment.sidepath_name`; the route description and the road panel say it
# where the way has no name.
SIDE_STREET_M = 20.0
SIDE_STREET_ANGLE = 30.0
SIDE_STREET_FRACTION = 0.6
# The trail is looked at every this many metres along it.
SIDE_STREET_STEP_M = 5.0
# The streets a bike lane is named after: roads a rider would know by name. Not a
# service road (a parking aisle, an alley), a track or a motorway.
SIDE_STREET_HIGHWAY = frozenset(
    {
        "trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link",
        "tertiary", "tertiary_link", "residential", "unclassified", "living_street",
    }
)  # fmt: skip
BIKE_LANE_WORDS = "bike lane"
PROTECTED_BIKE_LANE_WORDS = "protected bike lane"


def sidepath_name(street: str, tags: dict[str, str]) -> str:
    """ "<street> bike lane", or "<street> protected bike lane" where the way is tagged
    separated from the road or segregated."""
    protected = tags.get("segregated") == "yes" or any(
        _physical(tags.get(key)) for key in TRAIL_SEPARATION_KEYS
    )
    return f"{street} {PROTECTED_BIKE_LANE_WORDS if protected else BIKE_LANE_WORDS}"


def _bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    """The undirected bearing of a to b in the plane, degrees in [0, 180)."""
    return math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) % 180.0


def _angle_between(x: float, y: float) -> float:
    """The angle between two undirected bearings, 0-90."""
    d = abs(x - y) % 180.0
    return min(d, 180.0 - d)


def _samples(points: Sequence[tuple[float, float]], step: float):
    """(point, the bearing there, the metres it stands for) every `step` along a line."""
    for a, b in zip(points, points[1:], strict=False):
        length = math.dist(a, b)
        if length <= 0:
            continue
        bearing = _bearing(a, b)
        count = max(1, math.ceil(length / step))
        for k in range(count):
            t = (k + 0.5) / count
            yield (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])), bearing, length / count


def side_street_names(
    ways: Sequence[tuple[int, dict[str, str], Sequence[tuple[float, float]]]]
    | Iterable[tuple[int, dict[str, str], Sequence[tuple[float, float]]]],
) -> dict[int, str]:
    """Each unnamed bike way's name from the named street it runs alongside
    (`sidepath_name`), by osm id; ways with none are left out.

    `ways` is (osm id, tags, [(lon, lat), ...]). A way is asked when it is trail
    class, has no `name`, and a bicycle may ride it as a path or a protected lane
    (`facility`). It takes a street's name when at least SIDE_STREET_FRACTION of its
    length lies within SIDE_STREET_M of that street's centreline and within
    SIDE_STREET_ANGLE of parallel to it there. A street is a SIDE_STREET_HIGHWAY way
    with a `name`; two ways of one name count as one street."""
    lat0 = 38.9
    cell = SIDE_STREET_M
    # The candidates first, so only the streets near one are held (the region's named
    # roads are millions of segments; the unnamed bike ways a few thousand).
    ways = ways if isinstance(ways, Sequence) else list(ways)
    candidates: list[tuple[int, dict[str, str], list[tuple[float, float]]]] = []
    for osm_id, tags, coords in ways:
        if (
            len(coords) >= 2
            and tags.get("highway") in TRAIL_CLASS_HIGHWAY
            and not (tags.get("name") or "").strip()
            and facility(tags) in (Facility.PATH, Facility.PROTECTED)
        ):
            candidates.append((osm_id, tags, [_xy(lon, lat, lat0) for lon, lat in coords]))
    if not candidates:
        return {}
    wanted: set[tuple[int, int]] = set()
    for _osm_id, _tags, points in candidates:
        for p, _bearing_at, _metres in _samples(points, SIDE_STREET_STEP_M):
            wanted.add((int(p[0] // cell), int(p[1] // cell)))
    grid: dict[tuple[int, int], list[tuple[tuple[float, float], tuple[float, float], str]]] = {}
    for _osm_id, tags, coords in ways:
        name = (tags.get("name") or "").strip()
        if not name or tags.get("highway") not in SIDE_STREET_HIGHWAY or len(coords) < 2:
            continue
        points = [_xy(lon, lat, lat0) for lon, lat in coords]
        for a, b in zip(points, points[1:], strict=False):
            x0, x1 = sorted((a[0], b[0]))
            y0, y1 = sorted((a[1], b[1]))
            for gx in range(int(x0 // cell) - 1, int(x1 // cell) + 2):
                for gy in range(int(y0 // cell) - 1, int(y1 // cell) + 2):
                    if (gx, gy) in wanted:
                        grid.setdefault((gx, gy), []).append((a, b, name))
    found: dict[int, str] = {}
    for osm_id, tags, points in candidates:
        total = 0.0
        beside: dict[str, float] = {}
        for p, bearing, metres in _samples(points, SIDE_STREET_STEP_M):
            total += metres
            near: str | None = None
            nearest = SIDE_STREET_M
            for a, b, name in grid.get((int(p[0] // cell), int(p[1] // cell)), ()):
                d = _point_segment_m(p, a, b)
                if d <= nearest and _angle_between(bearing, _bearing(a, b)) <= SIDE_STREET_ANGLE:
                    near, nearest = name, d
            if near is not None:
                beside[near] = beside.get(near, 0.0) + metres
        if total <= 0 or not beside:
            continue
        street, metres = max(beside.items(), key=lambda item: (item[1], item[0]))
        if metres >= SIDE_STREET_FRACTION * total:
            found[osm_id] = sidepath_name(street, tags)
    return found


# --- The side path a `bicycle=use_sidepath` road asks riders to use (review RL-1) -----------

# The owner, 2026-10-16: "For the use-sidepath roads, make sure there's a sidepath
# marked." A road tagged `bicycle=use_sidepath` is rated Avoid only where a side path is
# mapped beside it: a trail-class way a bicycle may ride (a cycleway, a path, a footway or
# sidewalk open to bicycles; `trail_open_to_bicycle`) within USE_SIDEPATH_M of the road's
# centreline and within SIDE_STREET_ANGLE of parallel to it, along at least
# SIDE_STREET_FRACTION of the road's length. 30 m reaches a side path across a wide
# verge or a slip lane; the angle keeps a crosswalk or a path that only crosses out.
USE_SIDEPATH_M = 30.0


def is_use_sidepath_road(tags: dict[str, str]) -> bool:
    """A road (not a trail-class way) tagged `bicycle=use_sidepath` that nothing else
    closes: not a motorway or `motorroad=yes`, and no `access` or `vehicle` keeping the
    public out (`map_class` hides or bars those, and the remap closes them)."""
    highway = tags.get("highway")
    return (
        tags.get("bicycle") == USE_SIDEPATH
        and highway is not None
        and highway not in TRAIL_CLASS_HIGHWAY
        and highway not in BARRED_HIGHWAY
        and tags.get("motorroad") != "yes"
        and not any(tags.get(key) in NO_PUBLIC_ACCESS for key in ("access", "vehicle"))
    )


# The keys that put a side path on the road's own way: a cycle track
# (`cycleway*=track`), or a sidewalk open to bicycles (`sidewalk:*:bicycle`).
ON_ROAD_TRACK_KEYS = ("cycleway", "cycleway:left", "cycleway:right", "cycleway:both")
ON_ROAD_SIDEWALK_KEYS = (
    "sidewalk:bicycle",
    "sidewalk:left:bicycle",
    "sidewalk:right:bicycle",
    "sidewalk:both:bicycle",
)


def has_side_path_on_the_road(tags: dict[str, str]) -> bool:
    """Whether the road's own tags map its side path on it: a cycle track, or a
    sidewalk open to bicycles (`yes` or `designated`)."""
    return any(tags.get(key) == "track" for key in ON_ROAD_TRACK_KEYS) or any(
        tags.get(key) in ("yes", "designated") for key in ON_ROAD_SIDEWALK_KEYS
    )


def _is_crossing(tags: dict[str, str]) -> bool:
    return bool({tags.get(key) for key in CROSSING_KEYS} & {CROSSING, TRAFFIC_ISLAND})


def use_sidepath_paths(
    ways: Sequence[tuple[int, dict[str, str], Sequence[tuple[float, float]]]]
    | Iterable[tuple[int, dict[str, str], Sequence[tuple[float, float]]]],
) -> tuple[dict[int, str | None], set[int]]:
    """(each `bicycle=use_sidepath` road with a side path mapped beside it, by osm id, to
    that path's name or None where it has none; the roads with no side path found).

    `ways` is (osm id, tags, [(lon, lat), ...]). A road the tag does not leave open
    (`is_use_sidepath_road`), or with no length, is in neither. A side path on the
    road's own way (`has_side_path_on_the_road`) counts. Otherwise the road is looked
    at every SIDE_STREET_STEP_M; a step is covered where a bikeable trail-class way that
    is not a crossing lies within USE_SIDEPATH_M and within SIDE_STREET_ANGLE of
    parallel. The name is that of the named path covering the most of the road, where
    any does, and never the road's own name.

    Per way, not per segment: the graph carries one tier per way (the remap reads the
    way's tier), so a way split into Avoid and not-Avoid pieces would show the map one
    thing and route another."""
    lat0 = 38.9
    cell = USE_SIDEPATH_M
    ways = ways if isinstance(ways, Sequence) else list(ways)
    found: dict[int, str | None] = {}
    roads: list[tuple[int, str, list[tuple[float, float]]]] = []
    for osm_id, tags, coords in ways:
        if not is_use_sidepath_road(tags) or len(coords) < 2:
            continue
        points = [_xy(lon, lat, lat0) for lon, lat in coords]
        if sum(math.dist(a, b) for a, b in zip(points, points[1:], strict=False)) <= 0:
            continue
        if has_side_path_on_the_road(tags):
            found[osm_id] = None
            continue
        roads.append((osm_id, (tags.get("name") or "").strip().casefold(), points))
    if not roads:
        return found, set()
    wanted: set[tuple[int, int]] = set()
    for _osm_id, _name, points in roads:
        for p, _bearing_at, _metres in _samples(points, SIDE_STREET_STEP_M):
            wanted.add((int(p[0] // cell), int(p[1] // cell)))
    xs = [x for _i, _n, points in roads for x, _y in points]
    ys = [y for _i, _n, points in roads for _x, y in points]
    box = (min(xs) - cell, min(ys) - cell, max(xs) + cell, max(ys) + cell)
    grid: dict[tuple[int, int], list[tuple[tuple[float, float], tuple[float, float], str]]] = {}
    for _osm_id, tags, coords in ways:
        if (
            tags.get("highway") not in TRAIL_CLASS_HIGHWAY
            or tags.get("highway") == "steps"
            or len(coords) < 2
        ):
            continue
        points = [_xy(lon, lat, lat0) for lon, lat in coords]
        if (
            max(x for x, _y in points) < box[0]
            or min(x for x, _y in points) > box[2]
            or max(y for _x, y in points) < box[1]
            or min(y for _x, y in points) > box[3]
        ):
            continue
        cells: list[tuple[tuple[int, int], tuple[float, float], tuple[float, float]]] = []
        for a, b in zip(points, points[1:], strict=False):
            x0, x1 = sorted((a[0], b[0]))
            y0, y1 = sorted((a[1], b[1]))
            for gx in range(int(x0 // cell) - 1, int(x1 // cell) + 2):
                for gy in range(int(y0 // cell) - 1, int(y1 // cell) + 2):
                    if (gx, gy) in wanted:
                        cells.append(((gx, gy), a, b))
        if not cells or _is_crossing(tags) or not trail_open_to_bicycle(tags):
            continue
        name = (tags.get("name") or "").strip()
        for key, a, b in cells:
            grid.setdefault(key, []).append((a, b, name))
    missing: set[int] = set()
    for osm_id, road_name, points in roads:
        total = covered = 0.0
        named: dict[str, float] = {}
        for p, bearing, metres in _samples(points, SIDE_STREET_STEP_M):
            total += metres
            near: str | None = None
            nearest = USE_SIDEPATH_M
            for a, b, name in grid.get((int(p[0] // cell), int(p[1] // cell)), ()):
                d = _point_segment_m(p, a, b)
                if d <= nearest and _angle_between(bearing, _bearing(a, b)) <= SIDE_STREET_ANGLE:
                    near, nearest = name, d
            if near is not None:
                covered += metres
                if near and near.casefold() != road_name:
                    named[near] = named.get(near, 0.0) + metres
        if covered >= SIDE_STREET_FRACTION * total:
            found[osm_id] = (
                max(named.items(), key=lambda item: (item[1], item[0]))[0] if named else None
            )
        else:
            missing.add(osm_id)
    return found, missing


def use_sidepath_report_csv(rows: Iterable[tuple[int, str, str, str]]) -> str:
    """`use-sidepath-no-path.csv`: the `bicycle=use_sidepath` roads with no side path
    mapped beside them, rated on their own merits, for review as likely tagging errors.
    `rows` is (way id, name, county, state)."""

    def cell(text: str) -> str:
        return '"' + text.replace('"', '""') + '"' if any(c in text for c in ',"\n') else text

    lines = ["way_id,name,county,state"]
    for way_id, name, county, state in sorted(rows):
        lines.append(",".join([str(way_id), cell(name), cell(county), cell(state)]))
    return "\n".join(lines) + "\n"


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
