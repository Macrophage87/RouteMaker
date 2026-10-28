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

Then, 2026-10-21: "a lot of people would still ride on some lts 4 roads than take the
sidewalk, especially with sliplanes", choosing "Beside 4.5/Avoid only".

So two sets of footways are ridden (`rides`), and lua/routemaker_remap.lua prices them
(`rm:sidewalk`) at one of two levels:
- a link, and a sidewalk running beside a road rated 4.5 or Avoid (`beside`): costlier than
  any road up to LTS 3.5, cheaper than LTS 4, 4.5 and Avoid from the slider's middle up,
  rated LTS 3 (`TIER`);
- every other sidewalk and crosswalk (`LAST_RESORT`): a little costlier than an LTS 4 road
  at every slider position, so it is ridden only where nothing else connects or beside an
  Avoid road, rated LTS 4 (`LAST_RESORT_TIER`). The router prices LTS 4 and 4.5 roads alike,
  which is why the rebuild tells the two kinds apart rather than the price.
The ratings let the route's stress, the rolling stress chart and RouteMaker's own ranking
count them as the router prices them, not as a quiet trail.

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
  - never one barred to pedestrians, an area, or indoors.
- An informal connector (`is_informal_connector`, `informal=yes`, no bicycle tag) is a
  link only where the whole way is a short hop (`INFORMAL_WAY_MAX_M`), and it is walked,
  not ridden: the pipeline drops its `informal` closure and opens it as walk your bike
  (`pipeline.trail_closures.add_sidewalk_rides`). The owner reported, of Glen Haven Park
  in Silver Spring: "Some paths that have short sidewalk connections aren't
  available for routing". The park's paved path (OSM 597953361, `bicycle=yes`) meets
  Glenhaven Drive, Francis Drive and Huntley Avenue only through worn connectors of 36 to
  64 ft (11 to 20 m), every one `highway=path` + `informal=yes`, which the trail rules
  close (`trailaccess.INFORMAL`), so its one way in was Windham Lane and routes passed it
  by. Walking a bicycle is walking, so this widens nothing a pedestrian may not do.

- `cut_throughs`: a plain footway (no sidewalk, no bicycle tag) leaving a street's dead
  end for a ridden sidewalk or crosswalk, or another bicycle-open way that is no service
  road, within `CUT_THROUGH_M` (about 500 ft), ridden and priced as a link. The owner,
  2026-10-28, of the paved path from the end of Flack Street to the Glenmont Metro (OSM
  656592016, 290 ft, `highway=footway` and no bicycle tag): "This path was missed from
  the Glenmont metro", then chose "Rule: ride them, up to 500 ft". The street must be a
  public one (`STREET_HIGHWAY`): a parking lot is not a dead-end street.

None opens a footway something closes for a reason (`closed`: the CBD's sidewalks, a
military or secured area, the Zoo, an agency prohibition). Mass Ride's graph rides none of
them (`pipeline.run`).

Pure: `pipeline.trail_closures` calls `rides` with the rebuild's ways.
"""

from __future__ import annotations

import heapq
import math
from collections import defaultdict
from collections.abc import Callable, Sequence, Set

from . import tags as osm_tags
from . import trailaccess
from .facility import _angle_between, _bearing, _point_segment_m, _samples, _xy

# What a link, or a sidewalk beside a 4.5 or Avoid road, is rated: LTS 3, as the graph
# prices it (see the module's note).
TIER = 3
RULE = "sidewalk ridden as a last resort (the owner, 2026-10-20)"
# Every other ridden sidewalk and crosswalk: priced above an LTS 4 road, rated LTS 4.
LAST_RESORT = "last_resort"
LAST_RESORT_TIER = 4
LAST_RESORT_RULE = (
    "sidewalk beside a calmer road, ridden only where nothing else connects (the owner, 2026-10-21)"
)
# A sidewalk is beside a road when at least BESIDE_FRACTION of its length lies within
# BESIDE_M of the road's centreline (a wide verge or a slip lane between them) and within
# BESIDE_ANGLE of parallel to it, looked at every BESIDE_STEP_M.
BESIDE_M = 30.0
BESIDE_ANGLE = 30.0
BESIDE_FRACTION = 0.6
BESIDE_STEP_M = 5.0
SIDEWALK_KINDS = frozenset({"sidewalk", "crossing"})
# The longest gap a link may bridge, along the footways (about 160 ft).
GAP_M = 50.0
# The longest footway a link may open (about 1,000 ft).
WAY_MAX_M = 300.0
# The longest informal connector a link may open, walked (about 160 ft): the whole way,
# not just the part the gap uses, lies within the gap.
INFORMAL_WAY_MAX_M = GAP_M
# The longest walk a street-end cut-through may take (about 500 ft), along the footways it
# opens, each of which is wholly within it (`cut_throughs`).
CUT_THROUGH_M = 150.0

LINK_HIGHWAY = frozenset({"footway", "pedestrian"})
INFORMAL_HIGHWAY = frozenset({"footway", "path"})
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
# The streets a cut-through leaves from: public streets, never a service road (a parking
# lot or a driveway that meets the street through a footway is no cut-through).
STREET_HIGHWAY = frozenset(
    {"residential", "unclassified", "living_street", "tertiary", "tertiary_link", "road"}
)
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


def is_informal_connector(tags: dict[str, str]) -> bool:
    """A worn path or footway (`informal=yes`) no bicycle tag speaks for or against, open
    on foot: a link candidate where it is short, walked (see the module's note)."""
    if tags.get("highway") not in INFORMAL_HIGHWAY or tags.get("informal") != "yes":
        return False
    if any(key == "bicycle" or key.startswith("bicycle:") for key in tags):
        return False
    if tags.get("area") == "yes" or tags.get("indoor") not in (None, "no"):
        return False
    if tags.get("foot") in CLOSING_FOOT:
        return False
    return not _closed_by_its_tags(tags)


def takes_part(tags: dict[str, str]) -> bool:
    """A way `links` may open: its coordinates are read."""
    return is_link_candidate(tags) or is_informal_connector(tags)


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
    """Every footway ridden: the rideable sidewalks and crosswalks, the links and the
    cut-throughs."""
    found = set(links(ways, closed)) | set(cut_throughs(ways, closed))
    found.update(
        osm_id for osm_id, tags, _nodes, _coords in ways if osm_id not in closed and rideable(tags)
    )
    return found


def beside(
    sidewalks: Sequence[tuple[int, Sequence[tuple[float, float]]]],
    roads: Sequence[tuple[int, Sequence[tuple[float, float]]]],
) -> set[int]:
    """The sidewalks lying beside one of `roads`, each (osm id, [(lon, lat), ...]): at
    least BESIDE_FRACTION of the sidewalk's length within BESIDE_M of a road's centreline
    and within BESIDE_ANGLE of parallel to it there. A crosswalk, across the road, is never
    beside it."""
    lat0 = 38.9
    cell = BESIDE_M
    asked = [
        (osm_id, [_xy(lon, lat, lat0) for lon, lat in coords])
        for osm_id, coords in sidewalks
        if len(coords) >= 2
    ]
    if not asked or not roads:
        return set()
    wanted: set[tuple[int, int]] = set()
    for _osm_id, points in asked:
        for p, _bearing_at, _metres_at in _samples(points, BESIDE_STEP_M):
            wanted.add((int(p[0] // cell), int(p[1] // cell)))
    grid: dict[tuple[int, int], list[tuple[tuple[float, float], tuple[float, float]]]] = {}
    for _road_id, coords in roads:
        points = [_xy(lon, lat, lat0) for lon, lat in coords]
        for a, b in zip(points, points[1:], strict=False):
            # The cells along the segment and their neighbours, not its bounding box: a
            # long diagonal segment (a gap where a clipped extract lost nodes) stays linear.
            steps = max(1, math.ceil(math.dist(a, b) / (cell / 2)))
            cells = set()
            for k in range(steps + 1):
                x = a[0] + (b[0] - a[0]) * k / steps
                y = a[1] + (b[1] - a[1]) * k / steps
                cx, cy = int(x // cell), int(y // cell)
                cells.update((cx + i, cy + j) for i in (-1, 0, 1) for j in (-1, 0, 1))
            for key in cells & wanted:
                grid.setdefault(key, []).append((a, b))
    found: set[int] = set()
    for osm_id, points in asked:
        total = near = 0.0
        for p, bearing, metres in _samples(points, BESIDE_STEP_M):
            total += metres
            if any(
                _point_segment_m(p, a, b) <= BESIDE_M
                and _angle_between(bearing, _bearing(a, b)) <= BESIDE_ANGLE
                for a, b in grid.get((int(p[0] // cell), int(p[1] // cell)), ())
            ):
                near += metres
        if total > 0 and near >= BESIDE_FRACTION * total:
            found.add(osm_id)
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


def links(
    ways: Sequence[Placed], closed: Set[int] = frozenset(), walkable: Set[int] = frozenset()
) -> dict[int, float]:
    """The footways to open as links, each with the shortest gap (in
    metres) of a link it is part of. `ways` is (id, tags, node ids, a coordinate per
    node id, None where the extract has none; only a link candidate's are read, so
    other ways may carry none); `closed` the ways a closure rule closes; `walkable` the
    informal connectors (`is_informal_connector`) closed only for being informal, which
    take part as footways, never as bicycle-open ways, and only when the whole way is
    within INFORMAL_WAY_MAX_M. The caller walks those it finds.

    Two passes, so a region's million ways cost little: the footway network first, then
    the bicycle-open ways only at the nodes it reaches."""
    adjacent: dict[int, list[tuple[int, float, int]]] = defaultdict(list)
    lengths: dict[int, float] = {}
    informal: set[int] = set()
    for osm_id, tags, node_ids, coords in ways:
        if osm_id in closed or len(node_ids) < 2:
            continue
        if osm_id in walkable:
            informal.add(osm_id)
        elif not is_link_candidate(tags):
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
        if osm_id in closed or osm_id in walkable or len(node_ids) < 2 or not bicycle_open(tags):
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
        if any(lengths[way] > INFORMAL_WAY_MAX_M for way in used if way in informal):
            continue
        for way in used:
            found[way] = min(metres, found.get(way, metres))
    return found


def _shortest_gap(
    start: int,
    from_way: int,
    open_at: dict[int, int],
    adjacent: dict[int, list[tuple[int, float, int]]],
    gap_m: float = GAP_M,
) -> tuple[float, int, list[int]] | None:
    """The shortest way along candidate footways from `start` to a node another
    bicycle-open way reaches, within `gap_m`: (metres, that node, the footways used)."""
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
            if total <= gap_m and total < best.get(neighbour, math.inf):
                best[neighbour] = total
                previous[neighbour] = (node, way)
                heapq.heappush(queue, (total, neighbour))
    return None


def cut_throughs(ways: Sequence[Placed], closed: Set[int] = frozenset()) -> dict[int, float]:
    """The footways to open as street-end cut-throughs, each with the shortest walk (in
    metres) of a cut-through it is part of. `ways` as `links` takes them.

    A cut-through leaves a street's dead-end stretch (`STREET_HIGHWAY`; the stretch from
    the street's end that no other bicycle-open way reaches) along plain footways, ones no
    bicycle tag speaks for and that are not themselves sidewalks or crosswalks, to a node
    a ridden sidewalk or crosswalk (`rideable`) or another bicycle-open way that is no
    service road reaches, within CUT_THROUGH_M; each footway it opens lies wholly within
    CUT_THROUGH_M. The owner, 2026-10-28, of the paved path from the end of Flack Street
    to the Glenmont Metro (OSM 656592016, 290 ft): "This path was missed from the Glenmont
    metro", then chose "Rule: ride them, up to 500 ft"."""
    adjacent: dict[int, list[tuple[int, float, int]]] = defaultdict(list)
    lengths: dict[int, float] = {}
    rideable_at: set[int] = set()
    for osm_id, tags, node_ids, coords in ways:
        if osm_id in closed or len(node_ids) < 2:
            continue
        if rideable(tags):
            rideable_at.update(node_ids)
            continue
        if not is_link_candidate(tags):
            continue
        lengths[osm_id] = _length(coords)
        if lengths[osm_id] > CUT_THROUGH_M:
            continue
        for i in range(len(node_ids) - 1):
            a, b = coords[i], coords[i + 1]
            if a is None or b is None:
                continue
            step = _metres(a, b)
            adjacent[node_ids[i]].append((node_ids[i + 1], step, osm_id))
            adjacent[node_ids[i + 1]].append((node_ids[i], step, osm_id))
    if not adjacent:
        return {}

    # Each street end's stretch up to the first node a plain footway reaches: (street,
    # that node, the stretch's nodes). A loop has no end.
    stretches: list[tuple[int, int, list[int]]] = []
    for osm_id, tags, node_ids, _coords in ways:
        if (
            osm_id in closed
            or len(node_ids) < 2
            or node_ids[0] == node_ids[-1]
            or tags.get("highway") not in STREET_HIGHWAY
            or not bicycle_open(tags)
        ):
            continue
        for order in (node_ids, node_ids[::-1]):
            for i, node in enumerate(order):
                if node in adjacent:
                    stretches.append((osm_id, node, list(order[: i + 1])))
                    break
    if not stretches:
        return {}

    # The bicycle-open ways at the stretches' nodes and at the nodes the footways reach.
    asked = set(adjacent).union(*(set(nodes) for _street, _node, nodes in stretches))
    open_at: dict[int, set[int]] = defaultdict(set)
    service_at: dict[int, set[int]] = defaultdict(set)
    for osm_id, tags, node_ids, _coords in ways:
        if osm_id in closed or len(node_ids) < 2 or not bicycle_open(tags):
            continue
        service = tags.get("highway") == "service"
        for node in set(node_ids) & asked:
            (service_at if service else open_at)[node].add(osm_id)

    found: dict[int, float] = {}
    for street, start, nodes in stretches:
        if any(
            (open_at.get(node, set()) | service_at.get(node, set())) - {street} for node in nodes
        ):
            continue  # another bicycle-open way reaches the stretch: no dead end

        def arrived(node: int, street: int = street) -> bool:
            return node in rideable_at or bool(open_at.get(node, set()) - {street})

        walk = _shortest_walk(start, arrived, adjacent)
        if walk is None:
            continue
        metres, used = walk
        for way in used:
            found[way] = min(metres, found.get(way, metres))
    return found


def _shortest_walk(
    start: int,
    arrived: Callable[[int], bool],
    adjacent: dict[int, list[tuple[int, float, int]]],
    walk_m: float = CUT_THROUGH_M,
) -> tuple[float, list[int]] | None:
    """The shortest way along `adjacent`'s footways from `start` to a node `arrived`
    accepts, within `walk_m`: (metres, the footways used)."""
    best = {start: 0.0}
    previous: dict[int, tuple[int, int]] = {}
    queue = [(0.0, start)]
    while queue:
        metres, node = heapq.heappop(queue)
        if metres > best.get(node, math.inf):
            continue
        if node != start and arrived(node):
            used: list[int] = []
            at = node
            while at != start:
                at, way = previous[at]
                if way not in used:
                    used.append(way)
            return metres, used
        for neighbour, step, way in adjacent.get(node, ()):
            total = metres + step
            if total <= walk_m and total < best.get(neighbour, math.inf):
                best[neighbour] = total
                previous[neighbour] = (node, way)
                heapq.heappush(queue, (total, neighbour))
    return None
