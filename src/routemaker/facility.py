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
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from enum import StrEnum
from typing import NamedTuple

from .classes import MOTOR_ONLY_HIGHWAY, TRAIL_CLASS_HIGHWAY
from .ridetime import closed_settings
from .tags import (
    CYCLEWAY_KEYS,
    PERMISSIVE_ACCESS,
    best_direction_provision,
    cycleway_provision,
    cycleway_sides,
    is_oneway,
    narrow_access_lists,
    open_to_buses,
    parse_maxspeed_mph,
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
        # A zip-line or ropes course (Go Ape at Lake Needwood, tagged `highway=via_ferrata`: the
        # owner, 2026-10-22, "All of those things are for zip lining", "all of those structures but
        # beach drive should be taken out"; it drew as LTS 3). Valhalla routes no bicycle on one.
        "via_ferrata",
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
# don't need to show up." - "Sidewalks + small paths"; OWNER-DECISIONS 82),
# except one its own tags open to bicycles (`bicycle_link_service`).
HIDDEN_SERVICE = frozenset({"parking_aisle", "driveway", "drive-through"})
# What a hidden service way's own tags must say to be a link in the bicycle
# network instead: the same reading as the remap's `bicycle_link_service`
# (lua/routemaker_remap.lua, PR #197), which routes such a way as the service
# road it is. Pennyfield Lock Road's last 300 m to C&O Canal Lock 22 (way
# 137401070, `service=driveway` + `bicycle=yes`) was left off the map while it
# is the only road to the lock (owner report, 2026-10-19).
BICYCLE_LINK_GRANTS = frozenset({"yes", "designated", "permissive"})


def bicycle_link_service(tags: dict[str, str]) -> bool:
    """A parking aisle, driveway or drive-through its own tags open to bicycles,
    with no `access` or `vehicle` that restricts it: drawn and routed as a road."""
    return (
        tags.get("highway") == "service"
        and tags.get("service") in HIDDEN_SERVICE
        and tags.get("bicycle") in BICYCLE_LINK_GRANTS
        and all(tags.get(key, "yes") in PERMISSIVE_ACCESS for key in ("access", "vehicle"))
    )


# How short an unnamed footway or path has to be for the map to leave it out
# (82), unless it joins two trails the map keeps (`short_paths_to_hide`).
SHORT_PATH_M = 150.0
# A short link may be mapped in this many pieces (a bridge or a tunnel splits it)
# and still be kept as one (`short_paths_to_hide`); more is a web of paths, not a link.
SHORT_LINK_PIECES = 3


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
    parking aisle or driveway (unless its own tags open it to bicycles,
    `bicycle_link_service`), and a road or path the public may not enter
    (`access` or `vehicle` of no, private, military, restricted, permit), a
    bicycle or foot tag reopening it. Neither is drawn (OWNER-DECISIONS 89).
    "Legal but avoid" (an urban expressway, `bicycle=use_sidepath`) is a road a bicycle may
    use, and keeps its tier."""
    highway = tags.get("highway")
    if highway in NOT_A_WAY_HIGHWAY or tags.get("indoor", "no") != "no":
        return MapClass.HIDDEN
    if (
        highway == "service"
        and tags.get("service") in HIDDEN_SERVICE
        and not bicycle_link_service(tags)
    ):
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
    if bicycle == USE_SIDEPATH and side_path and not painted_lane_on_road(tags):
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
    parallels a protected bike path."; OWNER-DECISIONS 73, 78). The tag alone:
    the map's `separate_bikeway` also needs the bike way to be mapped beside it
    (`roads_with_bikeway_beside`). A trail-class way is the facility, not the road."""
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
    *,
    kinds: Collection[Facility] = (Facility.PATH,),
    step_m: float | None = None,
) -> tuple[set[int], set[int]]:
    """(the trails `beside_separate_roads` finds, the roads they lie beside).

    The second set is what the arterial floor (OWNER-DECISIONS 141) reads as
    "bike infrastructure": a road that says its facility is mapped separately
    and has such a trail along it. A named trail along it counts there too, though
    it stays a path in the first set.

    `kinds`: the classes a trail-class way may have by its own tags to be asked
    (a path by default). `step_m`: when given, each trail is looked at every that
    many metres along it rather than at its vertices only, so a long straight
    trail of two points still meets every road block it runs beside.
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
        if facility(tags) not in kinds:
            continue
        points = [_xy(lon, lat, lat0) for lon, lat in coords]
        if step_m is not None:
            points = [p for p, _bearing, _metres in _samples(points, step_m)]
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


def roads_with_bikeway_beside(
    ways: Iterable[tuple[int, dict[str, str], Sequence[tuple[float, float]]]],
) -> set[int]:
    """The roads the stress map draws faint and late as beside their own bike way
    (`segment.separate_bikeway`; OWNER-DECISIONS 73, 78): a road that says
    `cycleway*=separate` (`has_separate_bikeway`) AND has a bike way mapped along it,
    a path or a protected track by its own tags, looked at every SIDE_STREET_STEP_M.
    The tag alone is not enough: Connecticut Avenue NW from Davenport to Everett
    Street (OSM way 130908011) says it with only sidewalks beside it, and faded out
    with nothing to show in its place."""
    return separate_pairs(
        ways, kinds=(Facility.PATH, Facility.PROTECTED), step_m=SIDE_STREET_STEP_M
    )[1]


# --- An unnamed bike lane beside a named street (v0.7.0, "Go riding fixes" item 4) ------------

# The owner, 2026-10-15: "A protected bike lane was listed as an "unnamed path" near 9th
# and R NW." A cycleway or path with no name of its own that runs alongside a named street
# - within SIDE_STREET_M, roughly parallel (SIDE_STREET_ANGLE), for most of its length
# (SIDE_STREET_FRACTION) - is that street's bike lane: "9th Street Northwest bike lane",
# or "9th Street Northwest protected bike lane" where its tags say it is separated from
# the road (`separation*` physical) or segregated (`segregated=yes`), or, where people on
# foot share it, the path or the sidewalk beside that street ("sidewalk beside Kemp Mill
# Road"). The rebuild writes
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
# A path shared with people on foot beside a street is not a bike lane (the owner,
# 2026-11-03, of the sidewalk path beside Kemp Mill Road, OSM way 886775743, tagged
# `footway=sidewalk` + `bicycle=designated`: "Kemp Mill road doesn't have a bike lane").
# It is named as the route description names an unnamed path beside a major road at
# plan time (`describe.beside_words`): "path beside Kemp Mill Road".
SHARED_PATH_PREFIX = "path beside "
# A sidewalk signed for bicycles is still a sidewalk (the owner, 2026-11-03, of the same
# Kemp Mill Road way: "There's a narrow sidewalk which I wouldn't call a "path""):
# "sidewalk beside Kemp Mill Road", as `describe.beside_words` says it.
SHARED_SIDEWALK_PREFIX = "sidewalk beside "
# Every shared-way prefix, for reading a name back (`sidepath_street`).
SHARED_PREFIXES = (SHARED_PATH_PREFIX, SHARED_SIDEWALK_PREFIX)
# The `foot` values that say people on foot share the way.
SHARED_FOOT = frozenset({"yes", "designated", "permissive"})


def _is_sidewalk(tags: dict[str, str]) -> bool:
    return SIDEWALK in (tags.get("footway"), tags.get("path"), tags.get("cycleway"))


def shared_with_walkers(tags: dict[str, str]) -> bool:
    """True for a trail-class way people on foot share with bicycles, unsplit: a footway,
    path or sidewalk a bicycle may ride, or a cycleway open to foot, that is neither
    `segregated=yes` nor `foot=no`. A bare `highway=cycleway` says nothing of walkers,
    so is not."""
    if tags.get("segregated") == "yes" or tags.get("foot") == "no":
        return False
    if _is_sidewalk(tags):
        return True
    return tags.get("highway") != "cycleway" or tags.get("foot") in SHARED_FOOT


def sidepath_name(street: str, tags: dict[str, str]) -> str:
    """ "sidewalk beside <street>" for a sidewalk a bicycle may ride, even behind a kerb
    (`separation=kerb`); "<street> protected bike lane" where the way is tagged
    separated from the road or segregated (`segregated=yes` makes a sidewalk one too);
    else "path beside <street>" where people on foot share it (`shared_with_walkers`);
    else "<street> bike lane"."""
    segregated = tags.get("segregated") == "yes"
    if _is_sidewalk(tags) and shared_with_walkers(tags):
        return f"{SHARED_SIDEWALK_PREFIX}{street}"
    if segregated or any(_physical(tags.get(key)) for key in TRAIL_SEPARATION_KEYS):
        return f"{street} {PROTECTED_BIKE_LANE_WORDS}"
    if shared_with_walkers(tags):
        return f"{SHARED_PATH_PREFIX}{street}"
    return f"{street} {BIKE_LANE_WORDS}"


def sidepath_street(name: str | None) -> str | None:
    """The street a side-street name (`sidepath_name`) is named for ("K Street Northwest
    protected bike lane" -> "K Street Northwest", "path beside Kemp Mill Road" -> "Kemp
    Mill Road"), or None for any other name."""
    if not name:
        return None
    for prefix in SHARED_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix) :] or None
    for words in (PROTECTED_BIKE_LANE_WORDS, BIKE_LANE_WORDS):
        if name.endswith(" " + words):
            return name[: -len(words) - 1] or None
    return None


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
    (`sidepath_name`), by osm id; ways with none are left out (`side_streets`). A way with a
    name of its own, and a sidewalk a bicycle may merely use, are rated from the street but
    never named after it (`SideStreet.name` is empty)."""
    return {osm_id: found.name for osm_id, found in side_streets(ways).items() if found.name}


class SideStreet(NamedTuple):
    """The street a bike way runs alongside (`side_streets`, `on_road_tracks`).

    `name` and `metres_by_way` are read outside this module (the side-path names; PR #1242's
    `pipeline.run.weekend_car_free_beside`): keep both, in this order
    (tests/test_beside_busy_road.py pins them)."""

    # The way's name from the street (`sidepath_name`), or "" where the way is not named
    # after it: it has a name of its own, or is a sidewalk a bicycle may merely use.
    name: str
    # The metres of the bike way found beside each of the street's ways, by osm id (the share
    # of the street's level a way carries, for `stress.beside_busy_road_step`).
    metres_by_way: dict[int, float]
    # The street's own name ("Old Georgetown Road"): the path's OWN road, which it never
    # crosses by running beside it (`side_path_crossings`).
    street: str = ""
    # A rider may ride it against the traffic in the lane beside it: a two-way path or track
    # (one of its two directions always is), or a one-way one that points against that lane
    # (`CONTRAFLOW_FACTOR`).
    contraflow: bool = False
    # A sidewalk (`footway=sidewalk` and the like) open to bicycles.
    sidewalk: bool = False
    # A track or post-protected lane tagged on the road itself (`on_road_tracks`): the sides
    # of the road it is on. Empty for a way mapped on its own.
    road_sides: tuple[str, ...] = ()
    # And whether that is a painted lane behind posts or a kerb, not a track: the classifier
    # rates it as a painted lane, the side-path rule as the protected lane it is.
    posts: bool = False


_ONEWAY_FORWARD = frozenset({"yes", "true", "1"})
_ONEWAY_BACKWARD = frozenset({"-1", "reverse"})


def _ride_directions(tags: dict[str, str]) -> tuple[bool, bool]:
    """(forward, backward): the directions a bicycle may ride a trail-class way, along and
    against its nodes. `oneway:bicycle` first, then `oneway`; a way with neither is two-way,
    which is OSM's meaning for it and how the router rides it."""
    value = tags.get("oneway:bicycle") or tags.get("oneway")
    if value in _ONEWAY_FORWARD:
        return True, False
    if value in _ONEWAY_BACKWARD:
        return False, True
    return True, True


def asked_beside(tags: dict[str, str]) -> bool:
    """Whether a way is asked for the street it runs beside (`side_streets`): a trail-class
    way a bicycle may ride as a path or a protected lane (`facility`), or a sidewalk open to
    bicycles (`bicycle=yes`; its facility class is none, but it is ridden like the signed
    sidewalk beside it, and is rated like it). Its name is not part of the test."""
    highway = tags.get("highway")
    if highway not in TRAIL_CLASS_HIGHWAY or highway == "steps":
        return False
    if facility(tags) in (Facility.PATH, Facility.PROTECTED):
        return True
    return _is_sidewalk(tags) and trail_open_to_bicycle(tags)


def side_streets(
    ways: Sequence[tuple[int, dict[str, str], Sequence[tuple[float, float]]]]
    | Iterable[tuple[int, dict[str, str], Sequence[tuple[float, float]]]],
) -> dict[int, SideStreet]:
    """Each bike way's named street alongside, by osm id; ways with none are left out.

    `ways` is (osm id, tags, [(lon, lat), ...]). A way is asked when a bicycle may ride it as
    a path, a protected lane or an open sidewalk (`asked_beside`), named or not. It is beside
    a street when at least SIDE_STREET_FRACTION of its length lies within SIDE_STREET_M of
    that street's centreline and within SIDE_STREET_ANGLE of parallel to it there: geometry,
    never the lack of a name (the audit, 2026-11-13: the lanes named "Old Georgetown Road
    (MDBR 187)" were never asked). A street is a SIDE_STREET_HIGHWAY way with a `name`; two
    ways of one name count as one street.

    A trail with a name of its own (`named_for_itself`: "Capital Crescent Trail", not "15th
    Street Cycle Track") is judged as a whole: every way of that name in `ways`, taken
    together, must meet the same test against the one street. So a long trail is not a side
    path where a piece of it passes along a road, and a path that is a side path from end to
    end is one whatever it is called."""
    lat0 = 38.9
    cell = SIDE_STREET_M
    # The candidates first, so only the streets near one are held.
    ways = ways if isinstance(ways, Sequence) else list(ways)
    candidates: list[tuple[int, dict[str, str], list[tuple[float, float]]]] = []
    for osm_id, tags, coords in ways:
        if len(coords) >= 2 and asked_beside(tags):
            candidates.append((osm_id, tags, [_xy(lon, lat, lat0) for lon, lat in coords]))
    if not candidates:
        return {}
    wanted: set[tuple[int, int]] = set()
    for _osm_id, _tags, points in candidates:
        for p, _bearing_at, _metres in _samples(points, SIDE_STREET_STEP_M):
            wanted.add((int(p[0] // cell), int(p[1] // cell)))
    # (a, b, the street's name, its way, the way its traffic runs: 1 along a to b only, -1
    # against only, 0 both ways).
    grid: dict[
        tuple[int, int], list[tuple[tuple[float, float], tuple[float, float], str, int, int]]
    ] = {}
    for street_id, tags, coords in ways:
        name = (tags.get("name") or "").strip()
        if not name or tags.get("highway") not in SIDE_STREET_HIGHWAY or len(coords) < 2:
            continue
        flow = (-1 if tags.get("oneway") == "-1" else 1) if is_oneway(tags) else 0
        points = [_xy(lon, lat, lat0) for lon, lat in coords]
        for a, b in zip(points, points[1:], strict=False):
            x0, x1 = sorted((a[0], b[0]))
            y0, y1 = sorted((a[1], b[1]))
            for gx in range(int(x0 // cell) - 1, int(x1 // cell) + 2):
                for gy in range(int(y0 // cell) - 1, int(y1 // cell) + 2):
                    if (gx, gy) in wanted:
                        grid.setdefault((gx, gy), []).append((a, b, name, street_id, flow))
    # Each candidate's best street: (tags, total metres, the street, metres beside it, by
    # way, metres ridden forward with the lane beside less those against it).
    read: dict[int, tuple[dict[str, str], float, str | None, float, dict[int, float], float]] = {}
    for osm_id, tags, points in candidates:
        total = 0.0
        beside: dict[str, float] = {}
        by_way: dict[str, dict[int, float]] = {}
        with_flow: dict[str, float] = {}
        for start, end in zip(points, points[1:], strict=False):
            along = (end[0] - start[0], end[1] - start[1])
            for p, bearing, metres in _samples((start, end), SIDE_STREET_STEP_M):
                total += metres
                near = None
                nearest = SIDE_STREET_M
                for a, b, name, street_id, flow in grid.get(
                    (int(p[0] // cell), int(p[1] // cell)), ()
                ):
                    d = _point_segment_m(p, a, b)
                    if (
                        d <= nearest
                        and _angle_between(bearing, _bearing(a, b)) <= SIDE_STREET_ANGLE
                    ):
                        near, nearest = (a, b, name, street_id, flow), d
                if near is None:
                    continue
                a, b, name, street_id, flow = near
                beside[name] = beside.get(name, 0.0) + metres
                held = by_way.setdefault(name, {})
                held[street_id] = held.get(street_id, 0.0) + metres
                # The traffic in the lane nearest the path: the street's one way, or on a
                # two-way street the side the path is on (traffic keeps right).
                road = (b[0] - a[0], b[1] - a[1])
                if not flow:
                    left = road[0] * (p[1] - a[1]) - road[1] * (p[0] - a[0]) > 0
                    flow = -1 if left else 1
                same = (along[0] * road[0] + along[1] * road[1]) * flow > 0
                with_flow[name] = with_flow.get(name, 0.0) + (metres if same else -metres)
        if total <= 0:
            continue
        if not beside:
            read[osm_id] = (tags, total, None, 0.0, {}, 0.0)
            continue
        street, metres = max(beside.items(), key=lambda item: (item[1], item[0]))
        read[osm_id] = (tags, total, street, metres, by_way[street], with_flow[street])
    # A trail named for itself is judged over every way of its name.
    trail_total: dict[str, float] = {}
    trail_beside: dict[tuple[str, str], float] = {}
    own: dict[int, str] = {}
    for osm_id, (tags, total, street, metres, _by_way, _flow) in read.items():
        name = (tags.get("name") or "").strip()
        if not name:
            continue
        if street is not None and not named_for_itself(name, (street,)):
            continue
        key = _name_key(name)
        if not key or generic_facility_name(name):
            continue
        own[osm_id] = key
        trail_total[key] = trail_total.get(key, 0.0) + total
        if street is not None:
            trail_beside[key, street] = trail_beside.get((key, street), 0.0) + metres
    found: dict[int, SideStreet] = {}
    for osm_id, (tags, total, street, metres, by_way, flow) in read.items():
        if street is None or metres < SIDE_STREET_FRACTION * total:
            continue
        trail = own.get(osm_id)
        if trail is not None and (
            trail_beside.get((trail, street), 0.0) < SIDE_STREET_FRACTION * trail_total[trail]
        ):
            continue
        forward, backward = _ride_directions(tags)
        named = bool((tags.get("name") or "").strip())
        rated_only = named or facility(tags) is Facility.NONE
        found[osm_id] = SideStreet(
            "" if rated_only else sidepath_name(street, tags),
            by_way,
            street,
            contraflow=(forward and flow < 0) or (backward and flow >= 0),
            sidewalk=_is_sidewalk(tags),
        )
    return found


# --- A protected lane tagged on the road itself (the audit, 2026-11-13, I7) -----------------

# One level for one facility however it is mapped: a track tagged on the road
# (`cycleway*=track`), and a painted lane behind posts or a kerb (`cycleway*:separation`
# physical), are the same thing on the ground as a protected lane mapped as its own way, and
# go through the same rule (`stress.beside_busy_road_step`).


def on_road_tracks(
    ways: Iterable[tuple[int, dict[str, str], Sequence[tuple[float, float]]]],
) -> dict[int, SideStreet]:
    """The roads that carry a protected lane on their own way (`facility` is protected),
    by osm id, each as a side path beside itself: its street is its own name, and it is on
    the sides the tags say. Contraflow where a side says it is two-way
    (`cycleway:<side>:oneway=no`) or runs against a one-way's traffic."""
    found: dict[int, SideStreet] = {}
    for osm_id, tags, coords in ways:
        highway = tags.get("highway")
        if highway is None or highway in TRAIL_CLASS_HIGHWAY or highway in MOTOR_ONLY_HIGHWAY:
            continue
        if len(coords) < 2 or closed_to_motor_traffic(tags):
            continue
        if facility(tags) is not Facility.PROTECTED:
            continue
        sides = cycleway_sides(tags)
        rank = max(side.rank for side in sides.values())
        on = tuple(name for name, side in sides.items() if side.rank == rank)
        found[osm_id] = SideStreet(
            "",
            {osm_id: _length_m(coords)},
            (tags.get("name") or "").strip() or f"way {osm_id}",
            contraflow=any(sides[name].two_way or sides[name].contraflow for name in on),
            road_sides=on,
            posts=rank < 2,
        )
    return found


def without_bike_facility(tags: dict[str, str]) -> dict[str, str]:
    """A road's tags with every `cycleway*` key taken off: the road a rider in the roadway
    has, for the level a protected lane on it is never rated above
    (`stress.beside_busy_road_step`)."""
    return {key: value for key, value in tags.items() if not key.startswith("cycleway")}


# --- What a side path beside a busy road crosses (the owner, 2026-11-12) --------------------

# The owner, 2026-11-12: "Bike paths besides busy roads should get a bump. If there are lots of
# intersections, especially sliplanes it could get an even larger bump", and "it's not always
# number of crossings, but also how bad they are."
#
# A crossing point is a place where a rider FOLLOWING the path rides across the line of
# turning or crossing cars: a side-street mouth, a driveway, a service road, a slip lane (a
# `*_link`). Not one (the audit, 2026-11-13, I5):
# - the path's own road: the crosswalk over the street it runs beside, or the node where the
#   path ends by joining that street;
# - a crossing way the rider does not ride through: one with no side path of the same street
#   on its far side;
# - the end of the run, where the path stops at a street and goes no further.
#
# Each point costs feet of quiet riding on the junction model's scale
# (`crossing_point_ft`), summed over the run of side path along one street (its ways joined
# end to end, so a path split at every driveway is read as one) and read as feet a mile. A
# run under CROSSING_RUN_MIN_M is too short to read a rate from.

# The ways cars use that a side path can cross: streets, service roads and driveways, links.
CROSSING_HIGHWAY = frozenset(
    {
        "service", "residential", "unclassified", "living_street",
        "tertiary", "tertiary_link", "secondary", "secondary_link",
        "primary", "primary_link", "trunk", "trunk_link",
    }
)  # fmt: skip
# The level a crossed way is read at where the rebuild has none for it: a quiet street's.
# Our default; in a rebuild every road has a level.
UNRATED_CROSSING_LEVEL = 2.0
SLIP_LANE_HIGHWAY = frozenset({"trunk_link", "primary_link", "secondary_link", "tertiary_link"})
CROSSING_RUN_MIN_M = 160.0
_MILE_M = 1609.344
# Riding against the traffic in the lane beside the path, at an unsignalled point. Wachtel
# and Lewiston (1994, ITE Journal 64(9):30-35, Table 4) measured 4.5 times the collision
# risk for sidewalk riders going against the adjacent traffic over those going with it (2.0
# on the roadway, not significant); Schepers et al. (2011, Accident Analysis and Prevention
# 43(3):853-861, doi:10.1016/j.aap.2010.11.005) found more failure-to-yield crashes with
# through cyclists at unsignalised priority intersections with two-way tracks (abstract; no
# ratio taken from it). 2.0 is the low end of that range: OUR DEFAULT, not a measured value,
# and the level is one for both directions of a way, so a two-way path carries it for the
# rider going with the traffic as well (docs/stress/side-paths.md, known limits).
CONTRAFLOW_FACTOR = 2.0
# What a node says of the control there (`pipeline.extract.read_ways`' `control_nodes`).
SIGNAL_NODE = "signal"
STOP_NODE = "stop"
# How far along the crossed way, in its nodes either side of the point, a signal or the
# crossed way's own stop or yield sign is looked for (the junction model reads a signal up
# to 30 m along the crossed road, `core.junctions`; the rebuild has node order, not
# distance, here). Our default.
CONTROL_REACH_NODES = 2
# How many crossing ways and islands in a row are read as one crossing (a street crossed in
# two halves over a median island).
CROSSING_CHAIN_PIECES = 4


class SidePathCrossings(NamedTuple):
    """What a side path crosses (`side_path_crossings`): its run's crossing cost in feet of
    quiet riding a mile, the contraflow factor included (None where the run is too short to
    read a rate from), and whether the way itself crosses a slip lane."""

    ft_per_mile: float | None
    slip_lane: bool


def _length_m(coordinates: Sequence[tuple[float, float]]) -> float:
    lat0 = coordinates[0][1] if coordinates else 38.9
    points = [_xy(lon, lat, lat0) for lon, lat in coordinates]
    return sum(math.dist(a, b) for a, b in zip(points, points[1:], strict=False))


def _crossing_way(tags: dict[str, str]) -> bool:
    """A crossing mapped as its own way: a footway, cycleway or path tagged as the crossing
    (`footway=crossing`, `cycleway=crossing`, `path=crossing`), as DC, Arlington and
    Montgomery County map most crossings of a main road or a slip lane."""
    return tags.get("highway") in TRAIL_CLASS_HIGHWAY and "crossing" in (
        tags.get("footway"),
        tags.get("cycleway"),
        tags.get("path"),
    )


def _crossing_piece(tags: dict[str, str]) -> bool:
    """A crossing way, or the island between two of them."""
    return _crossing_way(tags) or (
        tags.get("highway") in TRAIL_CLASS_HIGHWAY
        and TRAFFIC_ISLAND in {tags.get(key) for key in CROSSING_KEYS}
    )


def _signalised(tags: dict[str, str]) -> bool:
    """A crossing way's own tags say it has a signal (as `pipeline.signals.is_signalised`)."""
    crossing = tags.get("crossing")
    if crossing == "traffic_signals":
        return tags.get("crossing:signals") != "no"
    return tags.get("crossing:signals") == "yes" and crossing not in {
        "uncontrolled", "unmarked", "no", "informal",
    }  # fmt: skip


def crossing_point_ft(
    level: float, highway: str = "", control: str | None = None, speed_mph: float | None = None
) -> float:
    """What one crossing point costs a rider on a side path, in feet of quiet riding: the
    junction model's own figure for crossing that way (`routemaker.intersections`, read
    only), so a signal, the crossed way's stop sign and the crossed way's level count as
    they do there.

    `level` is the crossed way's level, `highway` its class, `control` what is known of the
    control (SIGNAL_NODE, STOP_NODE for a stop or yield sign facing the crossed way's
    drivers, None for nothing mapped), `speed_mph` its posted speed where known.

    - A slip lane: `intersections.slip_ft` (1,000 ft; 500 ft at a signal). Charged once,
      here: the old extra half level for a slip lane is gone.
    - At a signal: `intersections.crossing_ft` at a signal (150 ft across LTS 3 or less,
      600 ft across LTS 4).
    - No signal, the crossed way at LTS 2.5 or more: `intersections.crossing_ft` from the
      stopped side, at `MARKED_CROSSING_FACTOR` as the model reads a path's crossing (800 ft
      across LTS 3, 2,000 ft and up across LTS 4), or the priority side where the crossed
      way faces a stop sign; never less than a quiet street's mouth.
    - No signal, a driveway or quiet street (below LTS 2.5), which the junction model does
      not price at all (`intersections.Road.busy`) and which are the points the owner asked
      to count: the model's own LTS 3 figure carried down in proportion to the level, a
      third of it a level (267 ft: a driveway at 1.5 is 400 ft, an LTS 2 street 533 ft). No
      number of ours; the straight line is our default, unmeasured. It is also the least
      any unsignalled point costs: a stop sign on the side street takes away the wait for
      a gap, not the driver who pulls across the path looking the other way.

    No right-hook term of its own: that charge is the junction model's
    (`intersections`, PR #1241), in its one table."""
    # Imported here: `intersections` reads `stress`, which reads this module.
    from . import intersections

    control_of = {
        SIGNAL_NODE: intersections.Control.SIGNAL,
        STOP_NODE: intersections.Control.CROSS_STOP,
    }.get(control, intersections.Control.NONE)
    if highway in SLIP_LANE_HIGHWAY:
        return intersections.slip_ft(control_of)
    tier = min(int(level), 5)
    road = intersections.Road(
        tier=tier,
        half=level % 1 == 0.5 and tier < 5,
        speed_mph=speed_mph,
        # A speed the model has to assume is not read as a rural road's (`intersections.scale`).
        urban=True,
    )
    if control_of is intersections.Control.SIGNAL:
        return intersections.crossing_ft(road, control_of, None)
    # A third of the model's unsignalled LTS 3 path crossing for each level, up to the last
    # level the model calls quiet.
    per_level = (
        intersections.STOPPED_CROSSING_FT[intersections.BUSY_TIER]
        * intersections.MARKED_CROSSING_FACTOR
        / intersections.BUSY_TIER
    )
    quiet = per_level * min(level, intersections.BUSY_TIER - 1.0)
    if not road.busy:
        return quiet
    gap = intersections.crossing_ft(road, control_of, None)
    if control_of is intersections.Control.NONE:
        gap *= intersections.MARKED_CROSSING_FACTOR
    return max(quiet, gap)


class _Crossed(NamedTuple):
    """One road at a node: its way, its name's key, what crossing it costs with no signal
    and at one, whether it is a slip lane, whether a signal is mapped within reach, whether
    the way ends at the node, and the next point along it from there."""

    way: int
    key: str
    ft: float
    signal_ft: float
    slip: bool
    signal: bool
    ends: bool
    toward: tuple[float, float] | None


def _street_key(osm_id: int, found: SideStreet) -> str:
    return _name_key(found.street or sidepath_street(found.name) or found.name) or f"way {osm_id}"


def side_path_crossings(
    ways: Sequence[tuple[int, dict[str, str], Sequence[int], Sequence[tuple[float, float]]]],
    side: dict[int, SideStreet],
    level_of: Callable[[int], float | None] | None = None,
    control_at: Mapping[int, str] | None = None,
    points: dict[int, dict] | None = None,
) -> dict[int, SidePathCrossings]:
    """For each side path in `side` (`side_streets`, `on_road_tracks`), what a rider
    following it crosses, by osm id.

    `ways` is (osm id, tags, node ids, [(lon, lat), ...]) for every way; `level_of` gives a
    crossed way's level by osm id (None where it has none); `control_at` gives the nodes
    tagged as a signal or a stop or yield sign (SIGNAL_NODE, STOP_NODE). What counts as a
    crossing point, and what does not, is in the note above; what each costs is
    `crossing_point_ft`. The two carriageways of one named street are one point. A run is
    the side paths along one street joined at shared end nodes or through a crossing the
    rider rides. Only the road nodes near a side path are held, so the region's road
    network is read, not kept. `points`, where given, is filled with each path's run's
    points, {point: (feet, signalised)}, for a report."""
    control_at = control_at or {}
    paths: dict[int, tuple[Sequence[int], float, str, Sequence[tuple[float, float]] | None]] = {}
    for osm_id, _tags, nodes, coords in ways:
        if osm_id in side:
            paths[osm_id] = (
                nodes,
                _length_m(coords),
                _street_key(osm_id, side[osm_id]),
                coords if len(coords) == len(nodes) else None,
            )
    path_nodes: dict[int, set[int]] = {}
    for path_id, (nodes, _length, _key, _coords) in paths.items():
        for node in nodes:
            path_nodes.setdefault(node, set()).add(path_id)
    # The crossing ways and islands within reach of a side path, each with its nodes and
    # whether its own tags say it has a signal.
    pieces: dict[int, tuple[Sequence[int], bool]] = {}
    for osm_id, tags, nodes, _coords in ways:
        if osm_id not in side and _crossing_piece(tags):
            pieces[osm_id] = (nodes, _signalised(tags))
    pieces_at: dict[int, list[int]] = {}
    for piece_id, (nodes, _signal) in pieces.items():
        for node in nodes:
            pieces_at.setdefault(node, []).append(piece_id)
    near: set[int] = set()
    frontier = {piece for node in path_nodes for piece in pieces_at.get(node, ())}
    for _hop in range(CROSSING_CHAIN_PIECES):
        frontier -= near
        if not frontier:
            break
        near |= frontier
        frontier = {
            other for piece in frontier for node in pieces[piece][0] for other in pieces_at[node]
        }
    wanted = set(path_nodes).union(*(pieces[piece][0] for piece in near))
    roads_at: dict[int, list[_Crossed]] = {}
    for osm_id, tags, nodes, coords in ways:
        highway = tags.get("highway", "")
        if highway not in CROSSING_HIGHWAY:
            continue
        hits = [index for index, node in enumerate(nodes) if node in wanted]
        if not hits:
            continue
        level = level_of(osm_id) if level_of is not None else None
        if level is None:
            level = UNRATED_CROSSING_LEVEL
        speed = parse_maxspeed_mph(tags.get("maxspeed"))
        key = _name_key(tags.get("name")) or f"way {osm_id}"
        located = coords if len(coords) == len(nodes) else None
        last = len(nodes) - 1
        for index in hits:
            reach = nodes[max(0, index - CONTROL_REACH_NODES) : index + CONTROL_REACH_NODES + 1]
            controls = {control_at.get(node) for node in reach}
            stop = STOP_NODE if STOP_NODE in controls else None
            ends = index in (0, last) and nodes[0] != nodes[last]
            toward = None
            if ends and located is not None and last >= 1:
                toward = located[1] if index == 0 else located[last - 1]
            roads_at.setdefault(nodes[index], []).append(
                _Crossed(
                    osm_id,
                    key,
                    crossing_point_ft(level, highway, stop, speed),
                    crossing_point_ft(level, highway, SIGNAL_NODE, speed),
                    highway in SLIP_LANE_HIGHWAY,
                    SIGNAL_NODE in controls,
                    ends,
                    toward,
                )
            )

    # Runs: the side paths of one street joined at shared end nodes or through a crossing
    # the rider rides.
    parent = {osm_id: osm_id for osm_id in paths}

    def root(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    ends_at: dict[tuple[str, int], int] = {}
    for osm_id, (nodes, _length, key, _coords) in paths.items():
        if not nodes:
            continue
        for node in (nodes[0], nodes[-1]):
            if (key, node) in ends_at:
                parent[root(osm_id)] = root(ends_at[key, node])
            else:
                ends_at[key, node] = osm_id

    # Each point as (its key, feet, signalised, slip lane), by the path that meets it:
    # where the path itself shares a node with the crossed way (`passes` counts the path's
    # way through the node: 2 through the middle, 1 at an end) ...
    direct: dict[int, list[tuple[int, tuple[str, object], float, bool, bool, int]]] = {}
    for path_id, (nodes, _length, key, coords) in paths.items():
        sides = side[path_id].road_sides
        last = len(nodes) - 1
        closed = last > 0 and nodes[0] == nodes[last]
        for index, node in enumerate(nodes):
            crossed = [
                road
                for road in roads_at.get(node, ())
                if road.key != key
                and road.way != path_id
                and not _other_side(sides, coords, index, road)
            ]
            if not crossed:
                continue
            worst = max(crossed, key=lambda road: road.ft)
            signal = any(road.signal for road in crossed) or control_at.get(node) == SIGNAL_NODE
            named = not worst.key.startswith("way ")
            direct.setdefault(path_id, []).append(
                (
                    node,
                    ("road", worst.key) if named else ("node", node),
                    max(road.signal_ft for road in crossed) if signal else worst.ft,
                    signal,
                    any(road.slip for road in crossed),
                    2 if closed or 0 < index < last else 1,
                )
            )
    # ... and where a crossing way (or a chain of them over an island) carries the rider
    # from one side path of the street to another. A piece over the path's own road is
    # never ridden by following the path, and is left out before the chain is read.
    chained: dict[int, list[tuple[tuple[str, object], float, bool, bool]]] = {}
    by_key: dict[str, list[int]] = {}
    for path_id, (_nodes, _length, key, _coords) in paths.items():
        by_key.setdefault(key, []).append(path_id)
    for key, members in by_key.items():
        own_nodes = {node for path_id in members for node in paths[path_id][0]}

        def rideable(piece: int, key: str = key, own_nodes: set[int] = own_nodes) -> bool:
            return not any(
                road.key == key
                for node in pieces[piece][0]
                if node not in own_nodes
                for road in roads_at.get(node, ())
            )

        seen: set[int] = set()
        for start in sorted({p for node in own_nodes for p in pieces_at.get(node, ())}):
            if start in seen or not rideable(start):
                continue
            chain = {start}
            edge = {start}
            while edge and len(chain) < CROSSING_CHAIN_PIECES:
                edge = {
                    other
                    for piece in edge
                    for node in pieces[piece][0]
                    if node not in own_nodes
                    for other in pieces_at[node]
                    if other not in chain and rideable(other)
                }
                chain |= edge
            seen |= chain
            chain_nodes = {node for piece in chain for node in pieces[piece][0]}
            touched = chain_nodes & own_nodes
            if len(touched) < 2:
                continue
            joined = sorted({p for node in touched for p in path_nodes[node] if p in members})
            for path_id in joined[1:]:
                parent[root(path_id)] = root(joined[0])
            crossed = [road for node in chain_nodes - own_nodes for road in roads_at.get(node, ())]
            if not crossed:
                continue
            worst = max(crossed, key=lambda road: road.ft)
            signal = (
                any(pieces[piece][1] for piece in chain)
                or any(road.signal for road in crossed)
                or any(control_at.get(node) == SIGNAL_NODE for node in chain_nodes)
            )
            named = not worst.key.startswith("way ")
            point = (
                ("road", worst.key) if named else ("way", min(chain)),
                max(road.signal_ft for road in crossed) if signal else worst.ft,
                signal,
                any(road.slip for road in crossed),
            )
            for path_id in joined:
                chained.setdefault(path_id, []).append(point)

    # A run's points: a shared node counts where the run goes through it (twice past it in
    # all), not where the run ends on it.
    run_length: dict[int, float] = {}
    run_passes: dict[int, dict[int, int]] = {}
    for path_id, (_nodes, length, _key, _coords) in paths.items():
        r = root(path_id)
        run_length[r] = run_length.get(r, 0.0) + length
        passes = run_passes.setdefault(r, {})
        for node, _point, _ft, _signal, _slip, count in direct.get(path_id, ()):
            passes[node] = passes.get(node, 0) + count
    run_points: dict[int, dict[tuple[str, object], tuple[float, bool]]] = {}
    slips: set[int] = set()

    def take(path_id: int, point: tuple[str, object], ft: float, signal: bool, slip: bool):
        held = run_points.setdefault(root(path_id), {})
        if point not in held or ft > held[point][0]:
            held[point] = (ft, signal)
        if slip:
            slips.add(path_id)

    for path_id in paths:
        passes = run_passes[root(path_id)]
        for node, point, ft, signal, slip, _count in direct.get(path_id, ()):
            if passes[node] >= 2:
                take(path_id, point, ft, signal, slip)
        for point, ft, signal, slip in chained.get(path_id, ()):
            take(path_id, point, ft, signal, slip)
    found: dict[int, SidePathCrossings] = {}
    for path_id in paths:
        r = root(path_id)
        factor = CONTRAFLOW_FACTOR if side[path_id].contraflow else 1.0
        feet = sum(ft if signal else ft * factor for ft, signal in run_points.get(r, {}).values())
        length = run_length[r]
        rate = feet / (length / _MILE_M) if length >= CROSSING_RUN_MIN_M else None
        found[path_id] = SidePathCrossings(rate, path_id in slips)
        if points is not None:
            points[path_id] = run_points.get(r, {})
    return found


def _other_side(
    sides: tuple[str, ...],
    coords: Sequence[tuple[float, float]] | None,
    index: int,
    road: _Crossed,
) -> bool:
    """Whether a way that ends at a road's node comes in from the side the road's track is
    not on (a track on one side only, `SideStreet.road_sides`): a rider in the track does
    not cross its mouth. A way that goes through the node is on both sides, and where the
    geometry is not known the point is kept."""
    if len(sides) != 1 or coords is None or not road.ends or road.toward is None:
        return False
    here = coords[index]
    before = coords[max(index - 1, 0)]
    after = coords[min(index + 1, len(coords) - 1)]
    lat0 = here[1]
    a, b, h, t = (_xy(lon, lat, lat0) for lon, lat in (before, after, here, road.toward))
    cross = (b[0] - a[0]) * (t[1] - h[1]) - (b[1] - a[1]) * (t[0] - h[0])
    if cross == 0:
        return False
    return ("left" if cross > 0 else "right") != sides[0]


# --- The side path a `bicycle=use_sidepath` road asks riders to use (review RL-1) -----------

# The owner, 2026-10-16: "For the use-sidepath roads, make sure there's a sidepath
# marked." A road tagged `bicycle=use_sidepath` is rated Avoid only where a side path is
# mapped beside it: a trail-class way a bicycle may ride (a cycleway, a path, a footway or
# sidewalk open to bicycles; `trail_open_to_bicycle`) within USE_SIDEPATH_M of the road's
# centreline and within SIDE_STREET_ANGLE of parallel to it, along at least
# SIDE_STREET_FRACTION of the road's length. 30 m reaches a side path across a wide
# verge or a slip lane; the angle keeps a crosswalk or a path that only crosses out.
USE_SIDEPATH_M = 30.0


# The `access` / `vehicle` values over which `bicycle=use_sidepath` opens nothing: no public
# access, and upstream's own closing values, over which it would read `use_sidepath` as a
# grant (the remap's `USE_SIDEPATH_CLOSING_ACCESS`, held equal by tests/test_facility.py).
USE_SIDEPATH_CLOSING_ACCESS = NO_PUBLIC_ACCESS | ACCESS_CLOSES


# The painted lanes that make a `bicycle=use_sidepath` road a mapping error (the owner,
# round 3, 2026-11-08: "If it has a painted lane and requires a sidepath then it's an OSM
# error" and "Bikes would be explicitly allowed"). Claude's default reading, not the owner's:
# a lane or buffered lane on either side. A contraflow-only lane (`opposite_lane`) is left
# out, since on a one-way road riders going with traffic have no lane there.
USE_SIDEPATH_ERROR_LANES = frozenset({"lane", "buffered_lane"})


def painted_lane_on_road(tags: dict[str, str]) -> bool:
    """Whether either side of the road carries a painted bike lane that makes its
    `bicycle=use_sidepath` a mapping error (`USE_SIDEPATH_ERROR_LANES`). Such a road is
    rated as its lane (`stress`), not listed as asking riders onto a side path
    (`use_sidepath_paths`) and not said to in the road panel (`bike_access_reason`)."""
    return any(side.value in USE_SIDEPATH_ERROR_LANES for side in cycleway_sides(tags).values())


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
        and not any(tags.get(key) in USE_SIDEPATH_CLOSING_ACCESS for key in ("access", "vehicle"))
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
        if not is_use_sidepath_road(tags) or painted_lane_on_road(tags) or len(coords) < 2:
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

    A link mapped in pieces counts as one (the owner, 2026-10-28, of a link from
    Percheron Trail under Airpark Road to Tree Farm Trail, split at its tunnel,
    both pieces hidden: "see why this trail isn't marked, and others like it"):
    short pieces joined where no kept trail meets them form a group. The group's
    dead ends are trimmed first (a spur to a bench, a loop hanging off the link:
    hidden, as each would be alone); what is left, up to SHORT_LINK_PIECES
    pieces, stays when it touches kept trails at two or more different nodes,
    on one trail or two, as a single way does.

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
    # The short pieces joined end to end, at a node no kept trail has.
    by_end: dict[int, list[int]] = {}
    for osm_id, ends in short.items():
        for node in set(ends):
            if node not in kept_nodes:
                by_end.setdefault(node, []).append(osm_id)
    hidden = set()
    seen: set[int] = set()
    for start in short:
        if start in seen:
            continue
        chain, stack = set(), [start]
        while stack:
            osm_id = stack.pop()
            if osm_id in chain:
                continue
            chain.add(osm_id)
            for node in short[osm_id]:
                stack.extend(by_end.get(node, ()))
        seen |= chain
        if len(chain) == 1:
            first, last = short[start]
            if not (first in kept_nodes and last in kept_nodes):
                hidden.add(start)
            continue
        link = _trim_dead_ends(chain, short, kept_nodes)
        hidden |= chain - link
        touching = {node for osm_id in link for node in short[osm_id] if node in kept_nodes}
        if len(link) > SHORT_LINK_PIECES or len(touching) < 2:
            hidden |= link
    return hidden


def _trim_dead_ends(
    chain: set[int], short: dict[int, tuple[int, int]], kept_nodes: set[int]
) -> set[int]:
    """`chain` less, over and over, each piece with an end that no kept trail and
    no other piece left has, and each closed piece: what is left runs between
    kept trails."""
    link = set(chain)
    while True:
        ends: dict[int, int] = {}
        for osm_id in link:
            for node in short[osm_id]:
                ends[node] = ends.get(node, 0) + 1
        dead = {
            osm_id
            for osm_id in link
            if short[osm_id][0] == short[osm_id][1]
            or any(node not in kept_nodes and ends[node] < 2 for node in short[osm_id])
        }
        if not dead:
            return link
        link -= dead
