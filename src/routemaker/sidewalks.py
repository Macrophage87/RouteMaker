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
(`rm:sidewalk`) at one of two levels, unless a rater rates one a side path (the last item):
- a link, a sidewalk running beside a road rated 4.5 or Avoid, or rated 4 with traffic at
  45 mph or more (`beside`, `pipeline.run.sidewalk_beats_road`; the fast level 4 road since
  the 2026-11-25 audit against Southwest Florida, where that is the usual artery), and a sidewalk
  beside no road at all (`roadless`: a walk joining two streets end to end, with no road to
  keep to): costlier than any road up to LTS 3.5, cheaper than LTS 4, 4.5 and Avoid from the
  slider's middle up, rated LTS 3 (`TIER`);
- every other sidewalk and crosswalk (`LAST_RESORT`): a little costlier than an LTS 4 road
  at every slider position, so it is ridden only where nothing else connects or beside an
  Avoid road, rated LTS 4 (`LAST_RESORT_TIER`). The router prices LTS 4 and 4.5 roads alike,
  which is why the rebuild tells the two kinds apart rather than the price.
- and one rated a side path (`SIDEPATH`): a ridden sidewalk whose override row, a rater's,
  rates it below LTS 3, priced as the path it is (the rater brief rates a sidewalk where the
  law lets bikes ride it from its own width, setback and driveways; "last resort" is the
  rater's call, never the map's tag alone).
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
- `trail_crossings`: a crosswalk with no bicycle tag, at most `GAP_M` long, that a trail
  meets at one of its ends and that reaches another bicycle-open way (the road it crosses
  at least), priced as a link: the crossing's stress belongs to the junction (Little Falls
  Parkway, 2026-11-19).
- `stubs`: a plain footway with no bicycle tag, at most `STUB_M` long, joining a trail to a
  ridden crosswalk, sidewalk or other bicycle-open way: the few metres a mapper draws at a
  corner, priced as a link (Ashburn Village Boulevard, 2026-11-27).
- `gap_links`: a run of footways with no bicycle tag, at most `GAP_M` long, whose ends meet
  bicycle-open ways (a trail among them) that the open network joins only by riding
  `GAP_DETOUR_M` or more, priced as a link: the owner, 2026-11-20, "Do a search for places
  that could match this and open them. This happens a lot."
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

- `cut_throughs`: a plain footway (`highway=footway`, no sidewalk, no bicycle tag, paved
  or of unknown surface, no hiking-trail marks) leaving a street's dead
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

from . import surfaces, trailaccess
from . import tags as osm_tags
from .facility import _angle_between, _bearing, _point_segment_m, _samples, _xy

# What a link, or a sidewalk beside a 4.5 or Avoid road, is rated: LTS 3, as the graph
# prices it (see the module's note).
TIER = 3
RULE = "sidewalk ridden as a last resort (the owner, 2026-10-20)"
# Every other ridden sidewalk and crosswalk: priced above an LTS 4 road, rated LTS 4.
LAST_RESORT = "last_resort"
# A ridden sidewalk an override row rates below `TIER` (a rater's side path; the rater
# brief, "Sidewalks where the law lets bikes ride them", 2026-11-26): priced as the path it
# is, not as a sidewalk (`pipeline.run.rated_sidepath_sidewalks`).
SIDEPATH = "sidepath"
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
# A gap link (`gap_links`) bridges two bicycle-open ways the open network itself joins only
# by riding at least this far (about 1,000 ft). Our default, unmeasured.
GAP_DETOUR_M = 300.0
# The longest footway `stubs` opens (about 30 ft): the join a mapper draws between a trail and
# the crosswalk or sidewalk at a corner. Our default, unmeasured.
STUB_M = 10.0
# How many footways off one dead-end stretch a cut-through is looked for from, nearest the
# end first (a short path to a door may leave nearer the end than the cut-through does).
STRETCH_FOOTWAYS = 4

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
# Tags that mark a footway as a hiking trail, which a cut-through never opens.
TRAIL_MARKS = ("sac_scale", "trail_visibility", "mtb:scale", "mtb:scale:imba")
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


def is_cut_through_candidate(tags: dict[str, str]) -> bool:
    """A footway `cut_throughs` may open: a link candidate that is no sidewalk or crosswalk,
    paved or of unknown surface, and with nothing marking it a hiking trail. Upstream closes
    a footway before the trail rules read its surface or difficulty
    (`trailaccess.verdict`), so they are read here."""
    if tags.get("highway") != "footway" or tags.get("footway") in SIDEWALK_KINDS:
        return False
    if any(key in tags for key in TRAIL_MARKS):
        return False
    if tags.get("surface") is not None and not surfaces.is_paved(tags):
        return False
    return is_link_candidate(tags)


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


# A sidewalk lies beside no road (`roadless`) when at most ROADLESS_FRACTION of its length
# is within ROADLESS_M of a road's centreline, square to one of its segments (level with
# it, not past a dead end) and within ROADLESS_ANGLE of parallel (a side street ending at it
# is not beside it). Our defaults, unmeasured, looser than `beside` on purpose: a sidewalk
# the beside test misses (a wide boulevard, a bend) is not taken for a connector.
ROADLESS_M = 45.0
ROADLESS_ANGLE = 45.0
ROADLESS_FRACTION = 0.2


def _alongside_m(p, a, b) -> float:
    """How far `p` is from the segment a-b, measured square to it, or infinity where it lies
    past either end: level with the road, not beyond its dead end or round a corner."""
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = -1.0 if length2 == 0 else ((px - ax) * dx + (py - ay) * dy) / length2
    if not 0.0 <= t <= 1.0:
        return math.inf
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def roadless(
    sidewalks: Sequence[tuple[int, Sequence[tuple[float, float]]]],
    roads: Sequence[tuple[int, Sequence[tuple[float, float]]]],
) -> set[int]:
    """The sidewalks lying beside no road, each (osm id, [(lon, lat), ...]): a walk tagged
    `footway=sidewalk` that joins two streets end to end, say, which the rebuild prices as a
    link rather than a last resort (`pipeline.run.last_resort_sidewalks`; the owner, of the
    walk joining the two ends of Briggs Road in Glenmont, OSM 656603494). A sidewalk with
    fewer than two points is never roadless."""
    lat0 = 38.9
    cell = ROADLESS_M
    asked = [
        (osm_id, [_xy(lon, lat, lat0) for lon, lat in coords])
        for osm_id, coords in sidewalks
        if len(coords) >= 2
    ]
    if not asked:
        return set()
    wanted: set[tuple[int, int]] = set()
    for _osm_id, points in asked:
        for p, _bearing_at, _metres_at in _samples(points, BESIDE_STEP_M):
            wanted.add((int(p[0] // cell), int(p[1] // cell)))
    grid: dict[tuple[int, int], list[tuple[tuple[float, float], tuple[float, float]]]] = (
        defaultdict(list)
    )
    for _road_id, coords in roads:
        if len(coords) < 2:
            continue
        points = [_xy(lon, lat, lat0) for lon, lat in coords]
        for a, b in zip(points, points[1:], strict=False):
            steps = max(1, math.ceil(math.dist(a, b) / (cell / 2)))
            cells = set()
            for k in range(steps + 1):
                x = a[0] + (b[0] - a[0]) * k / steps
                y = a[1] + (b[1] - a[1]) * k / steps
                cx, cy = int(x // cell), int(y // cell)
                cells.update((cx + di, cy + dj) for di in (-1, 0, 1) for dj in (-1, 0, 1))
            for key in cells & wanted:
                grid[key].append((a, b))
    found: set[int] = set()
    for osm_id, points in asked:
        total = near = 0.0
        for p, bearing, metres in _samples(points, BESIDE_STEP_M):
            total += metres
            if any(
                _alongside_m(p, a, b) <= ROADLESS_M
                and _angle_between(bearing, _bearing(a, b)) <= ROADLESS_ANGLE
                for a, b in grid.get((int(p[0] // cell), int(p[1] // cell)), ())
            ):
                near += metres
        if total > 0 and near <= ROADLESS_FRACTION * total:
            found.add(osm_id)
    return found


# The streets a drawn street link joins (`street_links`): public streets of every class,
# busy ones too (unlike a cut-through's `STREET_HIGHWAY`, which names where one starts),
# never a service road or a track (a parking lot's walk to the street is no link).
LINKED_STREET_HIGHWAY = OPEN_ROAD_HIGHWAY - {"service", "track", "cycleway"}


def street_links(
    ways: Sequence[tuple[int, dict[str, str], Sequence[int]]], candidates: Set[int]
) -> set[int]:
    """The `candidates` the map draws as links between streets: footways a bicycle may ride
    that the map would leave out (a sidewalk, a short unnamed path). Joined into runs at any
    node, a run is drawn where it meets public streets (`LINKED_STREET_HIGHWAY`, open to
    bicycles) at two or more different nodes, of one street or two (a walk cutting off a
    crescent's bend is a link too). The owner, of the walk joining the two ends
    of Briggs Road in Glenmont: "This is a useful link that should be included", then
    "Similar ones probably should as well". `ways` is (osm id, tags, node ids)."""
    nodes_of = {
        osm_id: frozenset(node_ids)
        for osm_id, _tags, node_ids in ways
        if osm_id in candidates and len(node_ids) >= 2
    }
    if not nodes_of:
        return set()
    wanted = set().union(*nodes_of.values())
    street_nodes: set[int] = set()
    for osm_id, tags, node_ids in ways:
        if (
            osm_id not in candidates
            and tags.get("highway") in LINKED_STREET_HIGHWAY
            and bicycle_open(tags)
        ):
            street_nodes.update(set(node_ids) & wanted)
    by_node: dict[int, list[int]] = defaultdict(list)
    for osm_id, nodes in nodes_of.items():
        for node in nodes:
            by_node[node].append(osm_id)
    found: set[int] = set()
    seen: set[int] = set()
    for start in nodes_of:
        if start in seen:
            continue
        run, stack = set(), [start]
        while stack:
            osm_id = stack.pop()
            if osm_id in run:
                continue
            run.add(osm_id)
            for node in nodes_of[osm_id]:
                stack.extend(by_node[node])
        seen |= run
        if len(set().union(*(nodes_of[osm_id] for osm_id in run)) & street_nodes) >= 2:
            found |= run
    return found


# A sidewalk of a street the public may not drive (`no_public_traffic_sidewalks`): one OSM
# opens to bicycles (`bicycle=yes` and the like) running beside a street closed to public
# motor traffic (`motor_vehicle=no` and the like: authorized vehicles at most), and beside no
# street the public drives. Stephen, 2026-11-22, of the walk beside Delaware Ave NE on the
# Capitol grounds, which routes left for a V of paths through Lower Senate Park 36% longer:
# "the path is so wide it's essentially a bike path, so it doesn't make sense to do that
# wierd kink", and "People with authorization can drive on it, but the sidewalks and paths
# are open to everyone". A sidewalk keeps a road's price (lua/routemaker_remap.lua,
# `M.priced_as_sidepath`) so a route keeps to the calm street beside it rather than ride
# among people walking; beside a street only authorized vehicles drive, the walk is one of
# the grounds' paths in all but its tag, and is priced as one.
SIDEWALK_GRANTS = frozenset({"yes", "designated", "permissive", "official"})
# The streets a sidewalk may run beside: every road class but cycleways and tracks, and
# pedestrian streets (closed to motor traffic by class).
SIDEWALK_STREET_HIGHWAY = (
    (OPEN_ROAD_HIGHWAY - {"cycleway", "track"}) | MOTORWAY_HIGHWAY | {"pedestrian"}
)


def _closed_to_public_driving(tags: dict[str, str]) -> bool:
    """A street the public may not drive by its own tags: `highway=pedestrian`, or `no` on
    the most specific of `motorcar`, `motor_vehicle`, `vehicle` and `access` the way carries
    (a list narrowed to its most restrictive part, as the transform reads it; `motor_vehicle=no`
    is OSM's tag for a street only authorized vehicles use), and no bus on it
    (`tags.open_to_buses`)."""
    if osm_tags.open_to_buses(tags):
        return False
    if tags.get("highway") == "pedestrian":
        return True
    tags = osm_tags.narrow_access_lists(tags)
    for key in ("motorcar", "motor_vehicle", "vehicle", "access"):
        value = tags.get(key)
        if value is not None:
            return osm_tags.most_restrictive(value) == "no"
    return False


def no_public_traffic_sidewalks(ways: Sequence[Placed]) -> set[int]:
    """The sidewalks (`footway=sidewalk`) OSM opens to bicycles that run beside a
    street closed to public driving (`_closed_to_public_driving`) and beside no street the
    public drives (`beside`)."""
    asked, closed, driven = [], [], []
    for osm_id, tags, _nodes, coords in ways:
        known = [c for c in coords if c is not None]
        if len(known) < 2:
            continue
        if tags.get("highway") == "footway" and tags.get("footway") == "sidewalk":
            if tags.get("bicycle") in SIDEWALK_GRANTS:
                asked.append((osm_id, known))
        elif tags.get("area") == "yes":
            continue
        elif tags.get("highway") in SIDEWALK_STREET_HIGHWAY:
            (closed if _closed_to_public_driving(tags) else driven).append((osm_id, known))
    if not asked or not closed:
        return set()
    found = beside(asked, closed)
    return found - beside([pair for pair in asked if pair[0] in found], driven)


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


def trail_crossings(ways: Sequence[Placed], closed: Set[int] = frozenset()) -> set[int]:
    """The crosswalks to price as links (`TIER`), not as last-resort sidewalks: a
    crosswalk (`footway=crossing`, a link candidate) at most `GAP_M` long that a
    trail-class bicycle-open way meets at one of its ends and that reaches another
    bicycle-open way (the road it crosses, or a way beyond: nearly always true, so the
    test that matters is the trail at an end). Unlike `links`, the trail need not stop
    there: it may run on past the crosswalk. `ways` as `links` takes them.

    The owner, 2026-11-19, of the Capital Crescent Trail at Little Falls Parkway: "It
    seemed to miss part of the bike lane next to little falls parkway", then chose
    "Build the rule". The parkway's separated path (OSM 1577282328, Little Falls Trail)
    leaves the trail's crossing and ends at Arlington Road on a marked crosswalk with no
    bicycle tag (778205176) across the parkway, which the last-resort price (LTS 4) made
    a wall: routes crossed both carriageways and rode the parkway instead. Crossing the
    road is the junction's stress, rated as a junction (the owner, 2026-11-15, crossings
    split), so the crosswalk itself takes a link's price, as a trail's dead-end footway
    link does. A crosswalk no trail meets at an end keeps the last-resort price: one that
    only crosses a cycle track on its way over the road is a pedestrian's crossing."""
    trail_at: dict[int, set[int]] = defaultdict(set)
    open_at: dict[int, set[int]] = defaultdict(set)
    crossings: list[tuple[int, Sequence[int], float]] = []
    for osm_id, tags, node_ids, coords in ways:
        if osm_id in closed or len(node_ids) < 2:
            continue
        if tags.get("footway") == "crossing" and is_link_candidate(tags):
            crossings.append((osm_id, node_ids, _length(coords)))
            continue
        if not bicycle_open(tags):
            continue
        trail = tags.get("highway") in TRAIL_HIGHWAY
        for node in node_ids:
            open_at[node].add(osm_id)
            if trail:
                trail_at[node].add(osm_id)
    found: set[int] = set()
    for osm_id, node_ids, metres in crossings:
        if not 0 < metres <= GAP_M:
            continue
        trails = trail_at.get(node_ids[0], set()) | trail_at.get(node_ids[-1], set())
        reached = set().union(*(open_at.get(node, ()) for node in node_ids))
        if trails and reached - trails:
            found.add(osm_id)
    return found


def stubs(ways: Sequence[Placed], closed: Set[int] = frozenset()) -> set[int]:
    """The joins to price as links (`TIER`): a plain footway with no bicycle tag (no
    sidewalk or crosswalk, which are ridden already), at most `STUB_M` long, with a trail
    at one end and, at the other, a ridden sidewalk or crosswalk or another bicycle-open way.
    `ways` as `links` takes them.

    The owner, 2026-11-27, at Ashburn Village Boulevard and Red Rum Drive: "Weird routing
    here". The side path (OSM 709050181, `bicycle=yes`) meets the corner's signalized
    crosswalk only through a 4 m footway with no tags (1138421927). Upstream closes it by
    its class, and the other rules miss it: the side path runs on past it (no dead end for
    `links`), the crosswalk is longer than a link and no trail ends on it
    (`trail_crossings`), and the corner's sidewalks join it into a run longer than a gap
    (`gap_links`). So the route rode 0.1 mi on along Red Rum Drive (LTS 3) and back on the
    side path to reach a path a step away."""
    trail_at: dict[int, set[int]] = defaultdict(set)
    open_at: dict[int, set[int]] = defaultdict(set)
    short: list[tuple[int, Sequence[int]]] = []
    for osm_id, tags, node_ids, coords in ways:
        if osm_id in closed or len(node_ids) < 2:
            continue
        if is_link_candidate(tags):
            if tags.get("footway") in SIDEWALK_KINDS:
                for node in (node_ids[0], node_ids[-1]):
                    open_at[node].add(osm_id)
            elif 0 < _length(coords) <= STUB_M:
                short.append((osm_id, node_ids))
            continue
        if not bicycle_open(tags):
            continue
        trail = tags.get("highway") in TRAIL_HIGHWAY
        for node in node_ids:
            open_at[node].add(osm_id)
            if trail:
                trail_at[node].add(osm_id)
    found: set[int] = set()
    for osm_id, node_ids in short:
        a, b = node_ids[0], node_ids[-1]
        for here, there in ((a, b), (b, a)):
            trails = trail_at.get(here, set())
            if trails and open_at.get(there, set()) - trails:
                found.add(osm_id)
                break
    return found


# The grid `gap_links` loads the open network on, in degrees (about 450 m north-south),
# and how many cells round each gap's end it loads: two, so a ride of `GAP_DETOUR_M` from
# an end stays on the loaded cells.
GAP_CELL_DEG = 0.004
GAP_CELL_REACH = 2


def _cell(point: tuple[float, float]) -> tuple[int, int]:
    return (math.floor(point[0] / GAP_CELL_DEG), math.floor(point[1] / GAP_CELL_DEG))


def gap_links(
    ways: Sequence[Placed],
    closed: Set[int] = frozenset(),
    locate: Callable[[int], Sequence[tuple[float, float] | None]] | None = None,
    also_open: Set[int] = frozenset(),
) -> set[int]:
    """The footways with no bicycle tag to price as links (`TIER`) because they close a gap:
    a run of link candidates (`is_link_candidate`: plain footways, sidewalks, crosswalks) at
    most `GAP_M` long whose ends meet two or more bicycle-open ways, a trail-class one among
    them, where the open network joins those ends only by riding `GAP_DETOUR_M` or more. A
    gap the network bridges nearby is left as it is (last resort, or closed).

    The owner, 2026-11-20, after Little Falls and the Medical Center side path: "Do a search
    for places that could match this and open them. This happens a lot." `links` opens a gap
    only where a bike way dead-ends; here the bike way may run on (a cycleway whose spur to
    a service road is a 35 m footway, OSM 39941547 by the Bethesda Trolley Trail), and the
    test is that nothing else nearby joins the two sides.

    `ways` as `links` takes them. `locate(i)` gives the coordinates (one per node id) of
    `ways[i]` where it carries none (the rebuild passes only link candidates'). `also_open`
    are footways another link rule opens, ridden as open ways here. Three passes, so a
    region costs little memory: the candidates and their runs, the open ways at their ends,
    then only the open ways near those ends for the searches. Pure."""
    candidates: dict[int, float] = {}
    nodes_of: dict[int, Sequence[int]] = {}
    coords_at: dict[int, tuple[float, float]] = {}

    def is_open(osm_id: int, tags: dict[str, str]) -> bool:
        return osm_id in also_open or bicycle_open(tags)

    for osm_id, tags, node_ids, coords in ways:
        if osm_id in closed or osm_id in also_open or len(node_ids) < 2:
            continue
        if is_link_candidate(tags) and len(coords) == len(node_ids):
            metres = _length(coords)
            if 0 < metres <= GAP_M:
                candidates[osm_id] = metres
                nodes_of[osm_id] = node_ids
                for k in (0, -1):
                    if coords[k] is not None:
                        coords_at[node_ids[k]] = coords[k]
    if not candidates:
        return set()
    parent = {w: w for w in candidates}

    def find(w: int) -> int:
        while parent[w] != w:
            parent[w] = parent[parent[w]]
            w = parent[w]
        return w

    at: dict[int, list[int]] = defaultdict(list)
    for osm_id in candidates:
        for node in set(nodes_of[osm_id]):
            at[node].append(osm_id)
    for here in at.values():
        for other in here[1:]:
            parent[find(other)] = find(here[0])
    del at
    runs: dict[int, list[int]] = defaultdict(list)
    for osm_id in candidates:
        runs[find(osm_id)].append(osm_id)
    run_ends = {
        root: {nodes_of[w][k] for w in run for k in (0, -1)}
        for root, run in runs.items()
        if sum(candidates[w] for w in run) <= GAP_M
    }
    # Pass two: the open ways at the runs' ends.
    end_nodes = set().union(*run_ends.values()) if run_ends else set()
    ways_at: dict[int, set[int]] = defaultdict(set)
    trail_at: set[int] = set()
    for osm_id, tags, node_ids, _coords in ways:
        if osm_id in closed or osm_id in candidates or not is_open(osm_id, tags):
            continue
        touched = end_nodes.intersection(node_ids)
        for node in touched:
            ways_at[node].add(osm_id)
        if touched and tags.get("highway") in TRAIL_HIGHWAY:
            trail_at.update(touched)
    gaps: dict[int, list[int]] = {}
    for root, ends in run_ends.items():
        met = sorted(e for e in ends if e in ways_at)
        if len(met) < 2 or trail_at.isdisjoint(met):
            continue
        if len(set().union(*(ways_at[e] for e in met))) >= 2:
            gaps[root] = met
    if not gaps:
        return set()
    # Pass three: the open ways near those ends, as a graph.
    cells: set[tuple[int, int]] = set()
    for met in gaps.values():
        for node in met:
            if node in coords_at:
                cx, cy = _cell(coords_at[node])
                cells.update(
                    (cx + dx, cy + dy)
                    for dx in range(-GAP_CELL_REACH, GAP_CELL_REACH + 1)
                    for dy in range(-GAP_CELL_REACH, GAP_CELL_REACH + 1)
                )
    adjacent: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for index, (osm_id, tags, node_ids, coords) in enumerate(ways):
        if osm_id in closed or osm_id in candidates or not is_open(osm_id, tags):
            continue
        if not coords and locate is not None:
            coords = locate(index)
        if len(coords) != len(node_ids):
            continue
        if not any(c is not None and _cell(c) in cells for c in coords):
            continue
        for k in range(len(node_ids) - 1):
            a, b = coords[k], coords[k + 1]
            if a is None or b is None:
                continue
            metres = _metres(a, b)
            adjacent[node_ids[k]].append((node_ids[k + 1], metres))
            adjacent[node_ids[k + 1]].append((node_ids[k], metres))

    def near(start: int, goals: set[int]) -> bool:
        """Whether the open network reaches a goal from `start` within GAP_DETOUR_M."""
        best = {start: 0.0}
        heap = [(0.0, start)]
        while heap:
            dist, node = heapq.heappop(heap)
            if dist > best.get(node, math.inf):
                continue
            if node in goals:
                return True
            for other, metres in adjacent.get(node, ()):
                step = dist + metres
                if step < GAP_DETOUR_M and step < best.get(other, math.inf):
                    best[other] = step
                    heapq.heappush(heap, (step, other))
        return False

    found: set[int] = set()
    for root, met in gaps.items():
        if any(not near(end, set(met) - {end}) for end in met):
            found.update(runs[root])
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
    the street's end that no other bicycle-open way reaches) along plain footways
    (`is_cut_through_candidate`), to a node
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
        if not is_cut_through_candidate(tags):
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

    # Each street end's stretch up to each of the first STRETCH_FOOTWAYS nodes a plain
    # footway reaches: (street, that node, the stretch's nodes). A loop has no end.
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
            tried = 0
            for i, node in enumerate(order):
                if node in adjacent:
                    stretches.append((osm_id, node, list(order[: i + 1])))
                    tried += 1
                    if tried == STRETCH_FOOTWAYS:
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
