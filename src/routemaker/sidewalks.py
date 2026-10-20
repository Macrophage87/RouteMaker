"""Sidewalks a bicycle may ride, as a last resort, and the short links where a bike way
stops at a footway.

The owner, riding Redland Road in Derwood on 2026-10-20: "When there's a tiny bit of
sidewalk before a bike lane it doesn't connect". The paved path from Lake Needwood
(OSM 710999916, `bicycle=designated`) ends on a sidewalk (448386707, `footway=sidewalk`,
no bicycle tag) about 120 ft (36 m) short of the Redland Road side path. Upstream's
transform closes a footway with no bicycle tag to bicycles by its class, so the path was
a dead end and routes could not use it. Then: "Bikes can go on sidewalks, especially in
more rural parts", and on the choice put to him, "Also sidewalks as last resort":
"Generally sidewalks adjacent to busy roads don't have a lot of pedestrian traffic so
it's less problematic. Not the most fun option".

So two sets of footways are ridden (`rides`), and lua/routemaker_remap.lua prices each as
a last resort (`rm:sidewalk`): costlier than any road up to LTS 3.5, cheaper than LTS 4,
4.5 and Avoid from the slider's middle up. The rebuild rates them LTS 3 (`TIER`), so the
route's stress, the rolling stress chart and RouteMaker's own ranking count them as the
router prices them, not as a quiet trail.

- `rideable`: a sidewalk or crosswalk (`footway=sidewalk` or `crossing`) no bicycle tag
  speaks for or against, open on foot. Riding a sidewalk is legal in DC outside the
  Central Business District (whose sidewalks keep their closure, `routemaker.cbd`) and in
  most of Maryland and Virginia; a town's own ban is not in the map data, and the owner
  chose to ride them all the same.
- `links`: where a way open to bicycles ends at a node no other bicycle-open way reaches (a
  dead end), and footways with no bicycle tag lead from it to another bicycle-open way
  within `GAP_M`, those footways, sidewalks or not. Bounds, so a link stays a link:
  - one end at least is a trail-class way (a path, cycleway, or a footway or bridleway
    open to bicycles): a parking lot joined to a street through a footway is not a link;
  - the gap is at most `GAP_M` (about 160 ft) along the footways;
  - each footway it opens is at most `WAY_MAX_M` (about 1,000 ft) long, since a tag opens
    the whole way and a router could ride any of it;
  - never one barred to pedestrians, an informal one, an area, or indoors.

Neither opens a footway something closes for a reason (`closed`: the CBD's sidewalks, a
military or secured area, the Zoo, an agency prohibition). Mass Ride's graph rides none of
them (`pipeline.run`).

Pure: `pipeline.trail_closures` calls `rides` with the rebuild's ways.
"""

from __future__ import annotations

import heapq
import math
from collections import defaultdict
from collections.abc import Sequence, Set

from . import tags as osm_tags
from . import trailaccess

# What a ridden sidewalk is rated: LTS 3, as the graph prices it (see the module's note).
TIER = 3
RULE = "sidewalk ridden as a last resort (the owner, 2026-10-20)"
SIDEWALK_KINDS = frozenset({"sidewalk", "crossing"})
# The longest gap a link may bridge, along the footways (about 160 ft).
GAP_M = 50.0
# The longest footway a link may open (about 1,000 ft).
WAY_MAX_M = 300.0

LINK_HIGHWAY = frozenset({"footway", "pedestrian"})
TRAIL_HIGHWAY = frozenset({"cycleway", "path", "footway", "pedestrian", "bridleway"})
# Classes upstream's transform opens to bicycles by default (lua/vendor/graph_upstream.lua);
# `steps` is left out: a flight of steps is no way to reach a bike lane.
OPEN_ROAD_HIGHWAY = frozenset(
    {
        "trunk",
        "trunk_link",
        "primary",
        "primary_link",
        "secondary",
        "secondary_link",
        "tertiary",
        "tertiary_link",
        "unclassified",
        "residential",
        "residential_link",
        "living_street",
        "service",
        "road",
        "track",
        "cycleway",
    }
)
MOTORWAY_HIGHWAY = frozenset({"motorway", "motorway_link"})
GRANTING_BICYCLE = trailaccess.UPSTREAM_BICYCLE_OPEN - trailaccess.PRIVATE_BICYCLE
CLOSING_ACCESS = trailaccess.UPSTREAM_ACCESS_CLOSED | trailaccess.PRIVATE_ACCESS
CLOSING_FOOT = frozenset({"no", "private", "use_sidepath"})

_EARTH_M = 6_371_008.8

Placed = tuple[int, dict[str, str], Sequence[int], Sequence[tuple[float, float] | None]]


def bicycle_open(tags: dict[str, str]) -> bool:
    """Whether the shipped transform leaves the way open to bicycles, from its tags."""
    highway = tags.get("highway")
    if highway in trailaccess.CANDIDATE_HIGHWAY:
        return trailaccess.upstream_open(tags)
    tags = osm_tags.narrow_access_lists(tags)
    bicycle = tags.get("bicycle")
    if highway in MOTORWAY_HIGHWAY:
        return bicycle in ("yes", "designated", "permissive", "official")
    if highway not in OPEN_ROAD_HIGHWAY:
        return False
    if bicycle is not None:
        return any(part.strip() in GRANTING_BICYCLE for part in bicycle.split(";"))
    if tags.get("access") in CLOSING_ACCESS or tags.get("vehicle") in CLOSING_ACCESS:
        return False
    return not (tags.get("impassable") == "yes" or tags.get("smoothness") == "impassable")


def is_trail(tags: dict[str, str]) -> bool:
    return tags.get("highway") in TRAIL_HIGHWAY and bicycle_open(tags)


def is_link_candidate(tags: dict[str, str]) -> bool:
    """A footway that may be ridden: one no bicycle tag speaks for or against, open on foot."""
    if tags.get("highway") not in LINK_HIGHWAY:
        return False
    if any(key == "bicycle" or key.startswith("bicycle:") for key in tags):
        return False
    if tags.get("area") == "yes" or tags.get("indoor") not in (None, "no"):
        return False
    if tags.get("foot") in CLOSING_FOOT or tags.get("informal") == "yes":
        return False
    if _closed_by_its_tags(tags):
        return False
    return trailaccess.upstream_open(tags) is False


def _closed_by_its_tags(tags: dict[str, str]) -> bool:
    """Closed for a reason besides the missing bicycle tag: an `access` or `vehicle`
    that grants less than the public, or impassable. The mark the remap writes reopens
    all of these, since upstream reads the bicycle key first, so they are left alone."""
    tags = osm_tags.narrow_access_lists(tags)
    for key in ("access", "vehicle"):
        value = tags.get(key)
        if value is not None and value not in osm_tags.PERMISSIVE_ACCESS:
            return True
    return tags.get("impassable") == "yes" or tags.get("smoothness") == "impassable"


def rideable(tags: dict[str, str]) -> bool:
    """A sidewalk or crosswalk ridden as a last resort."""
    return (
        tags.get("highway") == "footway"
        and tags.get("footway") in SIDEWALK_KINDS
        and is_link_candidate(tags)
    )


def rides(ways: Sequence[Placed], closed: Set[int] = frozenset()) -> set[int]:
    """Every footway ridden: the rideable sidewalks and crosswalks and the links."""
    found = set(links(ways, closed))
    found.update(
        osm_id for osm_id, tags, _nodes, _coords in ways if osm_id not in closed and rideable(tags)
    )
    return found


def _metres(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat0 = math.radians((a[1] + b[1]) / 2)
    dx = math.radians(b[0] - a[0]) * math.cos(lat0) * _EARTH_M
    dy = math.radians(b[1] - a[1]) * _EARTH_M
    return math.hypot(dx, dy)


def _length(coords: Sequence[tuple[float, float] | None]) -> float:
    known = [c for c in coords if c is not None]
    return sum(_metres(a, b) for a, b in zip(known, known[1:], strict=False))


# `links`' mark for a node two or more bicycle-open ways reach.
MANY = -1


def links(ways: Sequence[Placed], closed: Set[int] = frozenset()) -> dict[int, float]:
    """The footways to open as links, each with the shortest gap (in
    metres) of a link it is part of. `ways` is (id, tags, node ids, a coordinate per
    node id, None where the extract has none; only a link candidate's are read, so
    other ways may carry none); `closed` the ways a closure rule closes.

    Two passes, so a region's million ways cost little: the footway network first, then
    the bicycle-open ways only at the nodes it reaches."""
    adjacent: dict[int, list[tuple[int, float, int]]] = defaultdict(list)
    lengths: dict[int, float] = {}
    for osm_id, tags, node_ids, coords in ways:
        if osm_id in closed or len(node_ids) < 2 or not is_link_candidate(tags):
            continue
        lengths[osm_id] = _length(coords)
        for i in range(len(node_ids) - 1):
            a, b = coords[i], coords[i + 1]
            if a is None or b is None:
                continue
            step = _metres(a, b)
            adjacent[node_ids[i]].append((node_ids[i + 1], step, osm_id))
            adjacent[node_ids[i + 1]].append((node_ids[i], step, osm_id))

    # At each node the footways reach: the one bicycle-open way there, or MANY.
    open_at: dict[int, int] = {}
    trail_at: set[int] = set()
    ends: list[tuple[int, int]] = []
    trail_ways: set[int] = set()
    for osm_id, tags, node_ids, _coords in ways:
        if osm_id in closed or len(node_ids) < 2 or not bicycle_open(tags):
            continue
        trail = tags.get("highway") in TRAIL_HIGHWAY
        if trail:
            trail_ways.add(osm_id)
        for node in set(node_ids):
            if node not in adjacent:
                continue
            open_at[node] = osm_id if open_at.get(node, osm_id) == osm_id else MANY
            if trail:
                trail_at.add(node)
        if node_ids[0] != node_ids[-1]:
            ends.extend(((osm_id, node_ids[0]), (osm_id, node_ids[-1])))

    found: dict[int, float] = {}
    for osm_id, end in ends:
        if open_at.get(end) != osm_id:
            continue  # no footway meets it, or another bicycle-open way does: no dead end
        gap = _shortest_gap(end, osm_id, open_at, adjacent)
        if gap is None:
            continue
        metres, reached, used = gap
        if osm_id not in trail_ways and reached not in trail_at:
            continue  # neither end is a trail: not a link (a parking lot, a driveway)
        if any(lengths[way] > WAY_MAX_M for way in used):
            continue
        for way in used:
            found[way] = min(metres, found.get(way, metres))
    return found


def _shortest_gap(
    start: int,
    from_way: int,
    open_at: dict[int, int],
    adjacent: dict[int, list[tuple[int, float, int]]],
) -> tuple[float, int, list[int]] | None:
    """The shortest way along candidate footways from `start` to a node another
    bicycle-open way reaches, within GAP_M: (metres, that node, the footways used)."""
    best = {start: 0.0}
    previous: dict[int, tuple[int, int]] = {}
    queue = [(0.0, start)]
    while queue:
        metres, node = heapq.heappop(queue)
        if metres > best.get(node, math.inf):
            continue
        if node != start and open_at.get(node, from_way) != from_way:
            used: list[int] = []
            at = node
            while at != start:
                at, way = previous[at]
                if way not in used:
                    used.append(way)
            return metres, node, used
        for neighbour, step, way in adjacent.get(node, ()):
            total = metres + step
            if total <= GAP_M and total < best.get(neighbour, math.inf):
                best[neighbour] = total
                previous[neighbour] = (node, way)
                heapq.heappush(queue, (total, neighbour))
    return None
