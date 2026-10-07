"""The ways a rebuild closes to bicycles for the NO-BIKE-PATHS rules.

Pure: it takes the rebuild's ways and what the extract says about routes and
places, and answers which way gets which `rm:no_bicycle` reason
(`routemaker.trailaccess`, `routemaker.zoo`), which short `bicycle=dismount`
connectors stay and are flagged "walk your bike here" (OWNER-DECISIONS 291(5)),
and which ways are the Zoo's destination-only spur. `pipeline.run` calls it from
`classify_facilities` and writes the answers on the extract and the segment
table.

NPS units (291(6)): the tag rules apply now. A per-park "paved and designated
only" rule belongs in `PARK_RULES` below and is added only after that park's
published compendium has been read, which needs the owner's approval as a fetch;
none is fetched here, so the table is empty and `closures` consults it for
nothing yet.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field

from routemaker import cbd, facility, singletrack, trailaccess, zoo
from routemaker.cbd import Polygon

from .extract import Way
from .restricted_areas import MILITARY_NO_BICYCLE, SECURED_NO_BICYCLE, Area, ways_inside

# The hook for per-park rules (OWNER-DECISIONS 291(6): "Tags now, parks after
# review"). Keyed by the unit's OSM id, a value is the `rm:no_bicycle` reason
# for a rule that closes every unpaved way in the unit that is not designated
# for bicycles and not in a national bicycle route, once the unit's compendium
# has been checked. Empty on purpose.
PARK_RULES: Mapping[int, str] = {}

# Precedence, first match wins: a rule above has already said what the way is.
# A military area's closure (`restricted_areas.military_closures`) comes first: no graph
# reopens it, the off-road one included, whatever else the way is; and a secured
# federal compound's (`restricted_areas.secured_closures`, owner report 2026-10-06) next.
ORDER = (
    MILITARY_NO_BICYCLE,
    SECURED_NO_BICYCLE,
    "zoo",
    singletrack.NO_BICYCLE,
    cbd.NO_BICYCLE,
    *trailaccess.TAG_REASONS,
)

# Reasons that only the standard graphs close: the off-road graph keeps them
# open (OWNER-DECISIONS 291(2)).
OFFROAD_KEEPS = frozenset({trailaccess.MTB})
# Reasons whose ways a future mountain-bike mode would ride (`segment.mtb_only`).
MTB_ONLY = frozenset({trailaccess.MTB, singletrack.NO_BICYCLE})


@dataclass
class TrailClosures:
    # way id -> the `rm:no_bicycle` reason, from every rule here
    reasons: dict[int, str] = field(default_factory=dict)
    # short bicycle=dismount connectors kept, flagged for the route description
    walk_bike: set[int] = field(default_factory=set)
    # the Zoo spur: open, destination-only
    destination_only: set[int] = field(default_factory=set)

    def reason(self, osm_id: int) -> str | None:
        return self.reasons.get(osm_id)

    def mtb_only(self) -> set[int]:
        return {osm_id for osm_id, reason in self.reasons.items() if reason in MTB_ONLY}

    def counts(self) -> Counter:
        return Counter(self.reasons.values())


def park_paths(ways: Iterable[Way], park_areas: list[Area]) -> set[int]:
    """The plain `highway=path` ways inside a park or protected area."""
    placed = [(way.osm_id, way.tags, way.coordinates) for way in ways]
    return ways_inside(placed, park_areas, lambda tags: tags.get("highway") == "path")


def closures(
    ways: Iterable[Way],
    routes: Mapping[int, trailaccess.WayRoutes],
    park_areas: list[Area],
    zoo_polygon: list[Polygon] | None = None,
    military: Collection[int] = frozenset(),
    secured: Collection[int] = frozenset(),
) -> TrailClosures:
    """Every NO-BIKE-PATHS closure, by way, and the ways `military` names (closed
    inside a military area, owner report 2026-10-05) and `secured` names (closed
    inside a secured federal compound, 2026-10-06) under their own reasons."""
    ways = list(ways)
    result = TrailClosures()
    in_park = park_paths(ways, park_areas)
    chains = trailaccess.dismount_chains(
        (
            way.osm_id,
            way.tags,
            way.node_ids,
            facility._length_m(way.coordinates) if trailaccess.is_dismount(way.tags) else 0.0,
        )
        for way in ways
    )
    kept, long_dismount = trailaccess.dismount_reasons(chains)
    spur = zoo.spur_ways()
    for way in ways:
        osm_id, tags = way.osm_id, way.tags
        if osm_id in spur and osm_id not in military and osm_id not in secured:
            # Open and destination-only: no rule closes it (and nothing but the
            # Zoo rule would), so it is not asked.
            result.destination_only.add(osm_id)
            continue
        reason = None
        if osm_id in military:
            reason = MILITARY_NO_BICYCLE
        elif osm_id in secured:
            reason = SECURED_NO_BICYCLE
        elif zoo.closed_way(osm_id, tags, way.coordinates, zoo_polygon):
            reason = zoo.NO_BICYCLE
        elif singletrack.is_singletrack(tags):
            reason = singletrack.NO_BICYCLE
        elif cbd.barred_sidewalk(tags, way.coordinates):
            reason = cbd.NO_BICYCLE
        else:
            way_routes = routes.get(osm_id, trailaccess.NO_ROUTES)
            reason = trailaccess.verdict(tags, way_routes, osm_id in in_park)
            if reason is None and osm_id in long_dismount:
                reason = trailaccess.DISMOUNT
        if reason is not None:
            result.reasons[osm_id] = reason
        elif osm_id in kept:
            result.walk_bike.add(osm_id)
    return result
