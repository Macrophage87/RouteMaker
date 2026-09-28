"""Way classifications shared by the classifier and the tile build.

One definition, in one place. Two modules previously each declared a trail-class
set and each said in its docstring that the definition was fixed once; they
disagreed about `track`, so a rutted farm track classified as a comfortable
trail in one and as a roadway in the other.
"""

from __future__ import annotations

# Trail class, by `highway` alone and regardless of bicycle tag, because
# DC-area trails are tagged inconsistently and consulting the bicycle tag would
# classify the same trail differently along its length.
#
# `track` is deliberately absent. A track is an unpaved vehicle way, not a
# trail: it carries no separation guarantee, its ridability depends on
# `tracktype` and `smoothness`, and including it here would rate a grade5 farm
# track as comfortable for a child.
TRAIL_CLASS_HIGHWAY = frozenset({"cycleway", "footway", "path", "pedestrian", "bridleway", "steps"})

# Ways that are top-tier stress by classification alone, whatever else they are
# tagged. Named for what it asserts - a stress reading - rather than for access,
# which belongs to OSM's own `bicycle` and `access` tags and to the override
# table. `trunk` is deliberately absent: US-1, US-50 and New York Avenue NE are
# trunk here and are routinely bicycle-legal, so a blanket rule would be a
# derived access determination, which the plan reserves for an audited row. They
# reach LTS4 on their own speed and lane count anyway - which is true only
# because `trunk` and `trunk_link` are now in both default speed tables; while
# they were missing from both, an untagged one read as a 30 mph street and came
# out LTS3, and this comment was wrong about the thing it was defending. Going
# through the ordinary path also leaves their facility and shoulder tagging
# readable, which a short-circuit would discard.
ALWAYS_TOP_TIER_HIGHWAY = frozenset({"motorway", "motorway_link"})
MOTOR_ONLY_HIGHWAY = ALWAYS_TOP_TIER_HIGHWAY  # retained name for existing imports

# The trail-class ways a map zoomed out to the region still draws, and the ones
# it leaves for closer in (`core.stress_tiles`). Cycleways, paths and bridleways
# are the trail network a rider plans a ride around - the W&OD, the Capital
# Crescent, the park paths. Footways, pedestrian ways and steps are mostly
# sidewalks and plazas: 363,555 of the 414,836 trail-class segments in the first
# promoted build, drawn at region scale as a solid mesh over every street grid.
# Together the two are exactly TRAIL_CLASS_HIGHWAY.
TRAIL_NETWORK_HIGHWAY = frozenset({"cycleway", "path", "bridleway"})
SIDEWALK_CLASS_HIGHWAY = TRAIL_CLASS_HIGHWAY - TRAIL_NETWORK_HIGHWAY

# What a bicycle may do on a trail-class way, as the stress tiles need it
# (`trail_kind`). The rule is PUBLIC-DIALS's `routemaker.facility` rule for
# trail-class ways (wip/dials, 2026-09-27), restated here because that module
# is not on this branch; where the two meet, `routemaker.facility` is the one
# to keep and `trail_kind` should read it. The one part not restated is its
# geometric test for a trail lying beside a road that maps its facility
# separately, which needs the rebuild's geometry; such a trail reads "open"
# here and "protected" there, and both are drawn and kept zoomed out.
#
# Why it matters to the map: 3,831 trail-network ways in the 2026-09-25 extract
# are tagged bicycle=no, dismount or private - the Appalachian Trail, the
# Potomac Heritage Trail, the Bull Run-Occoquan Trail - and the map must not
# draw them as bike paths.
BICYCLE_ALLOWED = frozenset({"yes", "designated", "permissive", "official"})
TRAIL_OPEN_BY_DEFAULT = frozenset({"cycleway", "path"})
_PERMISSIVE_ACCESS = frozenset({"yes", "permissive", "designated", "official", "public"})
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
TRAIL_SEPARATION_KEYS = ("separation", "separation:left", "separation:right", "separation:both")

# Footways and paths that cross a road, or are the refuge in one, rather than
# leave it: 3,328 footway=crossing and 233 footway=traffic_island ways in the
# extract are open to bicycles. PUBLIC-DIALS's routemaker.facility makes them
# no facility whatever the bicycle tag, read from the footway= or path= key on
# any trail-class way (wip/dials 4f87d7e, CROSSING_KINDS); a trail's own
# crossing (highway=cycleway, cycleway=crossing) stays the trail's. The same
# here, so the two agree until trail_kind calls routemaker.facility.
CROSSING_KINDS = frozenset({"crossing", "traffic_island"})


class TrailKind:
    """What `trail_kind` answers; None is a way no bicycle rides as a trail
    (steps, a sidewalk a bicycle may merely use, a footway not signed for one)."""

    OPEN = "open to bicycles"  # an off-road path
    SIDEPATH = "sidepath for bicycles"  # the protected facility beside a road
    CLOSED = "not open to bicycles"  # a trail-network way a bicycle may not ride
    # A cycleway, path or bridleway a bicycle may ride that is no facility: a
    # crossing, or a sidewalk it may merely use. Named, because the plain text
    # of a cycleway or path is what a table from before the kinds were recorded
    # holds, and the zoomed-out map keeps those (pipeline.schema).
    NO_FACILITY = "no bicycle facility"


def trail_open_to_bicycle(tags: dict[str, str]) -> bool:
    """Whether a bicycle may ride a trail-class way, as Valhalla will read it."""
    bicycle = tags.get("bicycle")
    if bicycle is not None:
        return bicycle in BICYCLE_ALLOWED
    return tags.get("highway") in TRAIL_OPEN_BY_DEFAULT and all(
        tags.get(key) is None or tags[key] in _PERMISSIVE_ACCESS for key in ("access", "vehicle")
    )


def _physical(value: str | None) -> bool:
    return bool(value) and any(part.strip() in PHYSICAL_SEPARATION for part in value.split(";"))


def trail_kind(tags: dict[str, str]) -> str | None:
    """A trail-class way's `TrailKind`, or None."""
    highway = tags.get("highway")
    if highway not in TRAIL_CLASS_HIGHWAY or highway == "steps":
        return None
    network = highway in TRAIL_NETWORK_HIGHWAY
    if not trail_open_to_bicycle(tags):
        return TrailKind.CLOSED if network else None
    if any(tags.get(key) in CROSSING_KINDS for key in ("footway", "path")):
        return TrailKind.NO_FACILITY if network else None
    if "sidewalk" in (tags.get("footway"), tags.get("path"), tags.get("cycleway")):
        if tags.get("bicycle") == "designated":
            return TrailKind.SIDEPATH
        return TrailKind.NO_FACILITY if network else None
    if tags.get("is_sidepath") == "yes" or any(
        _physical(tags.get(key)) for key in TRAIL_SEPARATION_KEYS
    ):
        return TrailKind.SIDEPATH
    return TrailKind.OPEN
