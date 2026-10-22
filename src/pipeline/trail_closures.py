"""The ways a rebuild closes to bicycles for the NO-BIKE-PATHS rules.

Pure: it takes the rebuild's ways and what the extract says about routes and
places, and answers which way gets which `rm:no_bicycle` reason
(`routemaker.trailaccess`, `routemaker.zoo`), which short `bicycle=dismount`
connectors stay and are flagged "walk your bike here" (OWNER-DECISIONS 291(5)),
which sidewalks, crosswalks and short footway links are ridden as a last resort
(`routemaker.sidewalks`), and which ways are the Zoo's destination-only
spur. `pipeline.run` calls it from `classify_facilities` and writes the answers
on the extract and the segment table.

NPS units (291(6)): the tag rules apply now. A per-park "paved and designated
only" rule belongs in `PARK_RULES` below and is added only after that park's
published compendium has been read, which needs the owner's approval as a fetch;
none is fetched here, so the table is empty and `closures` consults it for
nothing yet.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Set
from dataclasses import dataclass, field

from routemaker import cbd, facility, sidewalks, singletrack, station_links, trailaccess, zoo
from routemaker.cbd import Polygon

from .extract import Way
from .restricted_areas import (
    GOLF_NO_BICYCLE,
    MILITARY_NO_BICYCLE,
    SECURED_NO_BICYCLE,
    TRACK_NO_BICYCLE,
    WORKS_NO_BICYCLE,
    Area,
    reopened_by_override,
    ways_inside,
)
from .variants import Variant

# The hook for per-park rules (OWNER-DECISIONS 291(6): "Tags now, parks after
# review"). Keyed by the unit's OSM id, a value is the `rm:no_bicycle` reason
# for a rule that closes every unpaved way in the unit that is not designated
# for bicycles and not in a national bicycle route, once the unit's compendium
# has been checked. Empty on purpose.
PARK_RULES: Mapping[int, str] = {}

# Precedence, first match wins: a rule above has already said what the way is.
# A military area's closure (`restricted_areas.military_closures`) comes first: no graph
# reopens it, the off-road one included, whatever else the way is; and a secured
# federal compound's (`restricted_areas.secured_closures`, owner report 2026-10-06) next,
# and a working site's (`restricted_areas.works_closures`, owner report 2026-10-12), and a
# golf course's (`restricted_areas.golf_closures`, owner report 2026-10-21), and a farm
# track's (`restricted_areas.track_closures`, owner report 2026-10-21).
ORDER = (
    MILITARY_NO_BICYCLE,
    SECURED_NO_BICYCLE,
    WORKS_NO_BICYCLE,
    GOLF_NO_BICYCLE,
    TRACK_NO_BICYCLE,
    "zoo",
    singletrack.NO_BICYCLE,
    cbd.NO_BICYCLE,
    *trailaccess.TAG_REASONS,
)

# Reasons that only the standard graphs close: the off-road graph keeps them
# open (OWNER-DECISIONS 291(2)). Since the owner's choice of 2026-10-19 ("Rated, MTB and
# Gravel") it keeps the drawn singletrack open as well, as the Mountain Bike graph does
# (`offroad_graph_keeps`).
OFFROAD_KEEPS = frozenset({trailaccess.MTB})
# Reasons whose ways the Mountain Bike ride type rides (`segment.mtb_only`).
MTB_ONLY = frozenset({trailaccess.MTB, singletrack.NO_BICYCLE})
# The Mountain Bike graph's own closure (`pipeline.variants.Variant.MTB`): a trail mapped
# closed when wet (`routemaker.mtbmode.closed_when_wet`), closed on that graph alone.
WET = "wet"


def mtb_graph_keeps(reason: str | None, osm_id: int, drawn_singletrack: Set[int]) -> bool:
    """Whether the Mountain Bike graph keeps a closed way open (docs/MTB-TOPO-PLAN.md, slice 6):
    the mountain-bike class (`mtb`), as the off-road graph does, and rated singletrack that
    nothing but its rating closes (`drawn_singletrack`, the ways the mountain-bike layer draws
    in their level's colour). A singletrack way that a tag rule would close without its rating
    (bicycle=no, a hiking-only footpath, private, a park rule, err closed) or a walk-your-bike
    way is not drawn, and so stays closed here too: bike-banned and hiking-only trails always
    stay closed (the owner's defaults of 2026-10-11). Every other reason stays closed."""
    if reason == trailaccess.MTB:
        return True
    return reason == singletrack.NO_BICYCLE and osm_id in drawn_singletrack


def offroad_graph_keeps(reason: str | None, osm_id: int, offroad_singletrack: Set[int]) -> bool:
    """Whether the off-road graph (Gravel, Mountain Goat) keeps a closed way open: the
    mountain-bike class, and, since the owner's choice of 2026-10-19 ("Rated, MTB and
    Gravel"), the drawn rated singletrack up to `singletrack.OFFROAD_MAX_LEVEL`
    (`offroad_singletrack`), which the Mountain Bike graph keeps too."""
    return reason in OFFROAD_KEEPS or (
        reason == singletrack.NO_BICYCLE and osm_id in offroad_singletrack
    )


def graph_reason(
    variant: Variant,
    reason: str | None,
    osm_id: int,
    drawn_singletrack: Set[int],
    wet_closed: Set[int],
    offroad_singletrack: Set[int] = frozenset(),
) -> str | None:
    """The `rm:no_bicycle` reason a way carries on one graph, or None for open: the
    rebuild's reason, less what the off-road graph keeps open (`OFFROAD_KEEPS`) and what the
    Mountain Bike graph keeps open (`mtb_graph_keeps`); on the Mountain Bike graph a way
    mapped closed when wet is closed (`WET`) whatever else it is."""
    if variant is Variant.OFFROAD and reason is not None:
        if reason in OFFROAD_KEEPS:
            reason = None
        elif offroad_graph_keeps(reason, osm_id, offroad_singletrack):
            # Rated singletrack (2026-10-19), and closed when wet as on the Mountain Bike graph.
            reason = WET if osm_id in wet_closed else None
    if variant is Variant.MTB:
        if mtb_graph_keeps(reason, osm_id, drawn_singletrack):
            reason = None
        if reason is None and osm_id in wet_closed:
            reason = WET
    return reason


@dataclass
class TrailClosures:
    # way id -> the `rm:no_bicycle` reason, from every rule here
    reasons: dict[int, str] = field(default_factory=dict)
    # short bicycle=dismount connectors kept, flagged for the route description
    walk_bike: set[int] = field(default_factory=set)
    # sidewalks, crosswalks and short footway links ridden as a last resort
    # (`routemaker.sidewalks`; the owner, 2026-10-20)
    sidewalk_rides: set[int] = field(default_factory=set)
    # the short links among them, where a bike way stops (`sidewalks.links`)
    sidewalk_links: set[int] = field(default_factory=set)
    # footways into rail stations, walked (`routemaker.station_links`), each also in
    # `walk_bike`
    walk_links: set[int] = field(default_factory=set)
    # the Zoo spur: open, destination-only
    destination_only: set[int] = field(default_factory=set)
    # rated singletrack that nothing but the rating closes: the map draws it on the
    # mountain-bike trail layer, in its level's colour (OWNER-DECISIONS 456; `drawn_singletrack`)
    drawn_singletrack: set[int] = field(default_factory=set)
    # the drawn singletrack the off-road graph rides too: up to singletrack.OFFROAD_MAX_LEVEL
    # (the owner's choice of 2026-10-19; `offroad_graph_keeps`)
    offroad_singletrack: set[int] = field(default_factory=set)

    def reason(self, osm_id: int) -> str | None:
        return self.reasons.get(osm_id)

    def mtb_only(self) -> set[int]:
        return {osm_id for osm_id, reason in self.reasons.items() if reason in MTB_ONLY}

    def counts(self) -> Counter:
        return Counter(self.reasons.values())


def mtb_level(reason: str | None, tags: dict[str, str]) -> int | None:
    """The difficulty level the rebuild writes (`segment.mtb_level`; OWNER-DECISIONS 456):
    `routemaker.singletrack.mtb_level` on a way closed as rated singletrack, None on every
    other. So a level always means closed on every graph, and the legend's "Not used for
    routes" holds for every coloured line: a mountain-bike-class way whose rating the
    singletrack rule does not read (`S2`, `0-2`) stays the grey dashes the off-road graph
    rides (review of slice 2)."""
    return singletrack.mtb_level(tags) if reason == singletrack.NO_BICYCLE else None


def drawn_singletrack(tags: dict[str, str], routes: trailaccess.WayRoutes, in_park: bool) -> bool:
    """Whether a rated singletrack way is drawn on the mountain-bike trail layer
    (OWNER-DECISIONS 454, 456; docs/MTB-TOPO-PLAN.md, slice 2): only where the rating is
    all that closes it. The tag rules it would meet without the rating (`trailaccess.
    verdict`: private, a park path, a footpath for walkers, err closed and the rest) and a
    walk-your-bike way keep it off the map, as they keep any other trail off it, so the
    layer never draws a trail a bicycle may not be allowed on ("err closed", 330). The
    mountain-bike class (`mtb`) is no such rule: it is the layer's own. A way upstream's
    own access reading already closes (`bicycle=no`, a footway with no bicycle tag) is not
    drawn either: `verdict` answers None for it only because there is nothing left to close.

    A natural surface with no bicycle tag (`natural_surface`) is no such rule on a rated
    trail (the owner's choice of 2026-10-19, "Rated, MTB and Gravel"): a difficulty rating
    means mappers saw bicycles ride it. Unrated, it stays closed (`trailaccess.verdict`)."""
    if trailaccess.is_dismount(tags) or not trailaccess.upstream_open(tags):
        return False
    return trailaccess.verdict(tags, routes, in_park) in RATING_OPENS


# The tag rules' answers that a difficulty rating does not overrule into a closure: none,
# the mountain-bike class, and a natural surface with no bicycle tag (2026-10-19).
RATING_OPENS = (None, trailaccess.MTB, trailaccess.NATURAL_SURFACE)


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
    reopened: Collection[int] = frozenset(),
    works: Collection[int] = frozenset(),
    golf: Collection[int] = frozenset(),
    tracks: Collection[int] = frozenset(),
) -> TrailClosures:
    """Every NO-BIKE-PATHS closure, by way, and the ways `military` names (closed
    inside a military area, owner report 2026-10-05) and `secured` names (closed
    inside a secured federal compound, 2026-10-06) and `works` names (closed inside a
    quarry, a landfill or an industrial area, 2026-10-12) and `golf` names (a golf
    course's cart paths and drives, 2026-10-21) and `tracks` names (a farm or forest
    track with no sign it is public, 2026-10-21) under their own reasons.

    `reopened` are the ways an approved access override wrote a bicycle key on. A
    mountain-bike-class way whose override lets a bicycle through is open, and so
    not `mtb_only` either: the map draws it as a way to ride, as the router rides it
    ("err closed", reopened by override with evidence; OWNER-DECISIONS 330). Any
    other bicycle key already ends the tag rules' closures (`trailaccess.verdict`)."""
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
        if osm_id in spur and not (
            osm_id in military
            or osm_id in secured
            or osm_id in works
            or osm_id in golf
            or osm_id in tracks
        ):
            # Open and destination-only: no rule closes it (and nothing but the
            # Zoo rule would), so it is not asked.
            result.destination_only.add(osm_id)
            continue
        reason = None
        if osm_id in military:
            reason = MILITARY_NO_BICYCLE
        elif osm_id in secured:
            reason = SECURED_NO_BICYCLE
        elif osm_id in works:
            reason = WORKS_NO_BICYCLE
        elif osm_id in golf:
            reason = GOLF_NO_BICYCLE
        elif osm_id in tracks:
            reason = TRACK_NO_BICYCLE
        elif zoo.closed_way(osm_id, tags, way.coordinates, zoo_polygon):
            reason = zoo.NO_BICYCLE
        elif singletrack.is_singletrack(tags):
            reason = singletrack.NO_BICYCLE
            if drawn_singletrack(
                tags, routes.get(osm_id, trailaccess.NO_ROUTES), osm_id in in_park
            ):
                result.drawn_singletrack.add(osm_id)
                level = singletrack.mtb_level(tags)
                if level is not None and level <= singletrack.OFFROAD_MAX_LEVEL:
                    result.offroad_singletrack.add(osm_id)
        elif cbd.barred_sidewalk(tags, way.coordinates):
            reason = cbd.NO_BICYCLE
        elif station_links.is_escalator(tags):
            # Never by bicycle (WMATA: "Use the elevators (never escalators)"); upstream
            # opens steps by class (`routemaker.station_links`, the owner, 2026-10-20).
            reason = station_links.ESCALATOR
        else:
            way_routes = routes.get(osm_id, trailaccess.NO_ROUTES)
            reason = trailaccess.verdict(tags, way_routes, osm_id in in_park)
            if reason == trailaccess.MTB and osm_id in reopened and reopened_by_override(tags):
                reason = None
            if reason is None and osm_id in long_dismount:
                reason = trailaccess.DISMOUNT
        if reason is not None:
            result.reasons[osm_id] = reason
        elif osm_id in kept:
            result.walk_bike.add(osm_id)
    return result


def add_sidewalk_rides(result: TrailClosures, ways: Iterable[Way]) -> None:
    """Find the footways ridden as a last resort (`routemaker.sidewalks`) once every closure
    is in `result.reasons`, the agency prohibitions included."""
    ways = list(ways)
    closed = set(result.reasons) | result.destination_only
    result.sidewalk_links = set(
        sidewalks.links(
            [
                (
                    way.osm_id,
                    way.tags,
                    way.node_ids,
                    node_coordinates(way) if sidewalks.is_link_candidate(way.tags) else (),
                )
                for way in ways
            ],
            closed=closed,
        )
    )
    result.sidewalk_rides = result.sidewalk_links | {
        way.osm_id for way in ways if way.osm_id not in closed and sidewalks.rideable(way.tags)
    }


def add_station_links(
    result: TrailClosures, ways: Iterable[Way], ways_in: Iterable[tuple[float, float]]
) -> None:
    """Open the footways into Metro and MARC stations as walk-your-bike links
    (`routemaker.station_links`; the owner, 2026-10-20), after every closure is in
    `result.reasons` and the ridden sidewalks are found (`add_sidewalk_rides`), and flag
    them `walk_bike`."""
    found = station_links.links(
        [
            (
                way.osm_id,
                way.tags,
                way.node_ids,
                node_coordinates(way) if sidewalks.is_link_candidate(way.tags) else (),
            )
            for way in ways
        ],
        ways_in,
        closed=set(result.reasons) | result.destination_only,
    )
    result.walk_links |= set(found)
    result.walk_bike |= set(found)
    # Walked, not ridden: a station's footway is no last-resort sidewalk.
    result.sidewalk_rides -= set(found)
    result.sidewalk_links -= set(found)


def node_coordinates(way: Way) -> list[tuple[float, float] | None]:
    """A coordinate per node id, None where the extract carries no location."""
    coords: list[tuple[float, float] | None] = [None] * len(way.node_ids)
    for index, lon, lat in way.located_points():
        coords[index] = (lon, lat)
    return coords
