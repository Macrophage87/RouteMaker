"""Walk-your-bike links into Metro and MARC stations, and escalators closed to bicycles.

The owner, riding to Shady Grove on 2026-10-20: "Somehow it missed one of the metro
entrances", "This station has a walking tunnel to get to it, not stairs" and "There are
several of these". The footways that lead into a station (its tunnels under the tracks,
the last stretch from the street to its elevator) mostly carry no bicycle tag, so
upstream's transform closes them by class and a route stopped at the last road, or went
the long way round to another side. The owner chose (2026-10-20, "Yes, walk your bike")
to open them at a walk: WMATA lets a bicycle into a station walked, by the elevator.

So, at every rail station: from each of its ways in (a `railway=subway_entrance` or
`train_station_entrance`, a street elevator near a station, the station node itself),
along the footways with no bicycle tag (`sidewalks.is_link_candidate`), two walks at
most: the shortest to a bicycle-open way, and the shortest to one through a tunnel (a
station's tunnel under the tracks leads to its other side), each within `WALK_MAX_M`.
Each footway on them becomes a `bicycle=dismount` link, "walk your bike here"
(`rm:walk_link`), as OSM's own short dismount connectors are, and is never ridden as a
last-resort sidewalk (`routemaker.sidewalks`). A walk stops at the first bicycle-open
way it meets: a way in, not a way round, so a way in on a sidewalk opens its nearest
crossing and no more. Never steps, never a footway a closure rule closes (the CBD's
sidewalks, a military or secured area), an indoor or informal one, an area, or one
longer than `WAY_MAX_M` (a tag opens the whole way, so a long sidewalk stays closed).

The same goes for the walkways at a platform that OSM tags `bicycle=yes` (`platform_walks`).
The owner, 2026-10-27: "For some strange reason the handicap ramp at the Kensington rail
station was marked as a bike path." The wheelchair ramp from Howard Avenue down to the
MARC platform there (way 772035684), the walkways along the station building and the
crossing over the tracks between the platforms all carry `bicycle=yes` from one mapper's
edit of the station, so a route counted them as a traffic-free path and rode them. A
bicycle may use them, so they stay open, but they are a station's walkways, not a bike
path: each unnamed footway or path that `bicycle=yes` (or `permissive`) opens and that
joins a `railway=platform`, or joins one within `PLATFORM_REACH_M` of it along such
walkways, is walked too (`rm:platform_walk`), and is no facility. A named way or one
`bicycle=designated` is a trail someone signed and is left alone, as is one longer than
`WAY_MAX_M`.

And an escalator (`highway=steps` with `conveying`) is closed to bicycles whatever its
tags say (`ESCALATOR`): WMATA: "Use the elevators (never escalators)". Upstream opens
steps to bicycles by class.

Pure: `pipeline.station_links.read_ways_in` reads the extract's ways in, and
`pipeline.trail_closures` asks `links` with the rebuild's ways.
"""

from __future__ import annotations

import heapq
import math
from collections import defaultdict
from collections.abc import Iterable, Sequence, Set

from .sidewalks import Placed, bicycle_open, is_link_candidate

# The `rm:no_bicycle` reason for an escalator.
ESCALATOR = "escalator"

# The longest walk from a way in to a bicycle-open way, along the footways (about 800 ft):
# Shady Grove's tunnel under the tracks is about 260 ft, and its walk to the street
# elevator about 200 ft more.
WALK_MAX_M = 250.0
# A footway node this close to a way in starts a walk (about 80 ft): an elevator or an
# entrance is often mapped beside the footway it serves, not on it.
SEED_M = 25.0
# A footway node this close to a way in is the way in itself.
ON_WAY_IN_M = 1.0
# The longest footway a walk may open (about 500 ft): shorter than a walk link's, since a
# station's walks run along downtown sidewalks, and a tag opens the whole way.
WAY_MAX_M = 150.0
# How far along a station's walkways from its platform a walkway may begin and still be
# walked (about 33 ft): far enough for the short ways at a platform's end (Kensington's
# ramp meets the station building's walkways 4 m from the platform), not out into the
# parking lot beyond.
PLATFORM_REACH_M = 10.0
# The bicycle values that open a platform walkway; `designated` is a signed trail.
PLATFORM_WALK_BICYCLE = frozenset({"yes", "permissive"})
PLATFORM_WALK_HIGHWAY = frozenset({"footway", "path"})
# A street elevator counts as a way in within this of a station node (about 1,000 ft).
ELEVATOR_STATION_M = 300.0

_EARTH_M = 6_371_008.8


def is_escalator(tags: dict[str, str]) -> bool:
    return tags.get("highway") == "steps" and tags.get("conveying") not in (None, "no")


def is_way_in(tags: dict[str, str]) -> bool:
    """A node that is a rail station's own way in."""
    return tags.get("railway") in ("subway_entrance", "train_station_entrance")


def is_station(tags: dict[str, str]) -> bool:
    """A rail station's node (a bus station's is not one)."""
    return tags.get("railway") == "station" and tags.get("station") not in ("bus", "monorail")


def _metres(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat0 = math.radians((a[1] + b[1]) / 2)
    dx = math.radians(b[0] - a[0]) * math.cos(lat0) * _EARTH_M
    dy = math.radians(b[1] - a[1]) * _EARTH_M
    return math.hypot(dx, dy)


def ways_in(
    entrances: Iterable[tuple[float, float]],
    stations: Sequence[tuple[float, float]],
    elevators: Iterable[tuple[float, float]],
) -> list[tuple[float, float]]:
    """The points walks start from: every entrance, the elevators within
    ELEVATOR_STATION_M of a station (an elevator elsewhere is a building's), and a station
    node only where neither is mapped near it (it is often mid-block, over the platform)."""
    entrances = list(entrances)
    near = [e for e in elevators if any(_metres(e, s) <= ELEVATOR_STATION_M for s in stations)]
    ways = entrances + near
    bare = [s for s in stations if not any(_metres(s, w) <= ELEVATOR_STATION_M for w in ways)]
    return ways + bare


class _Grid:
    """Points by a cell about SEED_M across, for the ways in near a node."""

    def __init__(self, points: Iterable[tuple[float, float]]) -> None:
        self.cells: dict[tuple[int, int], list[tuple[int, tuple[float, float]]]] = defaultdict(list)
        for index, point in enumerate(points):
            self.cells[self._cell(point)].append((index, point))

    @staticmethod
    def _cell(point: tuple[float, float]) -> tuple[int, int]:
        # 0.0003 degrees is about 33 m north-south and 26 m east-west in this region.
        return (math.floor(point[0] / 0.0003), math.floor(point[1] / 0.0003))

    def near(self, point: tuple[float, float], metres: float) -> list[tuple[int, float]]:
        """The ways in within `metres` of `point`: (index, metres)."""
        cx, cy = self._cell(point)
        found = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for i, other in self.cells.get((cx + dx, cy + dy), ()):
                    m = _metres(point, other)
                    if m <= metres:
                        found.append((i, m))
        return found


def is_tunnel(tags: dict[str, str]) -> bool:
    return tags.get("tunnel") not in (None, "no") or tags.get("layer", "").startswith("-")


def links(
    ways: Sequence[Placed],
    points: Iterable[tuple[float, float]],
    closed: Set[int] = frozenset(),
) -> dict[int, float]:
    """The footways to open as walk-your-bike links into a station, each with the
    shortest walk (metres) it is part of. `ways` as `sidewalks.links` takes them (only a
    link candidate's coordinates are read); `points` the ways in (`ways_in`); `closed`
    the ways a closure rule closes.

    From each way in, the walk to the nearest bicycle-open way, and the nearest through
    a tunnel (a station's tunnel under the tracks leads to its other side): two walks at
    most, so a way in on a sidewalk opens its nearest crossing, not every one in reach."""
    grid = _Grid(points)
    if not grid.cells:
        return {}
    adjacent: dict[int, list[tuple[int, float, int]]] = defaultdict(list)
    tunnels: set[int] = set()
    # Each way in's footway nodes within SEED_M, with how far each is from it.
    seeds: dict[int, dict[int, float]] = defaultdict(dict)
    for osm_id, tags, node_ids, coords in ways:
        if osm_id in closed or len(node_ids) < 2 or not is_link_candidate(tags):
            continue
        steps = [
            (i, _metres(a, b))
            for i, (a, b) in enumerate(zip(coords, coords[1:], strict=False))
            if a is not None and b is not None
        ]
        if sum(m for _i, m in steps) > WAY_MAX_M:
            continue  # a tag opens the whole way: a long one is never a link
        if is_tunnel(tags):
            tunnels.add(osm_id)
        for node, coord in zip(node_ids, coords, strict=False):
            if coord is not None:
                for way_in, metres in grid.near(coord, SEED_M):
                    seeds[way_in][node] = min(metres, seeds[way_in].get(node, metres))
        for i, step in steps:
            adjacent[node_ids[i]].append((node_ids[i + 1], step, osm_id))
            adjacent[node_ids[i + 1]].append((node_ids[i], step, osm_id))
    if not seeds:
        return {}

    open_at: set[int] = set()
    for osm_id, tags, node_ids, _coords in ways:
        if osm_id in closed or len(node_ids) < 2 or not bicycle_open(tags):
            continue
        open_at.update(node for node in node_ids if node in adjacent)

    found: dict[int, float] = {}
    for starts in seeds.values():
        # A way in mapped on a footway starts there alone: no node near it cuts its walk short.
        on = {node: m for node, m in starts.items() if m <= ON_WAY_IN_M}
        starts = on or starts
        for metres, used in _walks(starts, adjacent, open_at, tunnels):
            for way in used:
                found[way] = min(metres, found.get(way, metres))
    return found


State = tuple[int, bool]


def _walks(
    starts: dict[int, float],
    adjacent: dict[int, list[tuple[int, float, int]]],
    open_at: Set[int],
    tunnels: Set[int],
) -> list[tuple[float, list[int]]]:
    """From one way in's nodes (each starting at its distance from the way in), the
    shortest walk to a bicycle-open way, and the shortest that goes through a tunnel, within
    WALK_MAX_M: (metres, the footways used) each. A walk stops at the first bicycle-open way
    it meets: a way in, not a way round."""
    best: dict[State, float] = {}
    previous: dict[State, tuple[State, int]] = {}
    queue: list[tuple[float, int, bool]] = []
    for node, metres in starts.items():
        best[(node, False)] = metres
        queue.append((metres, node, False))
    heapq.heapify(queue)
    ends: dict[bool, tuple[float, State]] = {}
    while queue and len(ends) < 2:
        metres, node, tunnelled = heapq.heappop(queue)
        state = (node, tunnelled)
        if metres > best.get(state, math.inf):
            continue
        if node in open_at:
            if state in previous:
                ends.setdefault(tunnelled, (metres, state))
            continue
        for neighbour, step, way in adjacent.get(node, ()):
            total = metres + step
            after = (neighbour, tunnelled or way in tunnels)
            if total <= WALK_MAX_M and total < best.get(after, math.inf):
                best[after] = total
                previous[after] = (state, way)
                heapq.heappush(queue, (total, *after))
    walks = []
    for metres, state in ends.values():
        used: list[int] = []
        while state in previous:
            state, way = previous[state]
            if way not in used:
                used.append(way)
        walks.append((metres, used))
    return walks


# A platform's own tags that say a passenger service stops at it: a park's miniature
# railway's or a disused line's platform says none of them.
PLATFORM_SERVICE_KEYS = ("train", "light_rail", "subway", "tram")
PLATFORM_LIFECYCLE_KEYS = ("disused", "abandoned", "historic")


def is_platform(tags: dict[str, str]) -> bool:
    """A rail platform in service: `railway=platform` with `public_transport=platform` or
    a rail mode tagged on it (a bus stop's `public_transport=platform` alone is not one,
    nor is a miniature railway's or a disused line's)."""
    if tags.get("railway") != "platform":
        return False
    if any(tags.get(key) not in (None, "no") for key in PLATFORM_LIFECYCLE_KEYS):
        return False
    return tags.get("public_transport") == "platform" or any(
        tags.get(key) == "yes" for key in PLATFORM_SERVICE_KEYS
    )


def is_platform_walk_candidate(tags: dict[str, str]) -> bool:
    """An unnamed footway or path that `bicycle=yes` or `permissive` opens: a station's
    walkway when it meets a platform (`platform_walks`)."""
    return (
        tags.get("highway") in PLATFORM_WALK_HIGHWAY
        and tags.get("bicycle") in PLATFORM_WALK_BICYCLE
        and not tags.get("name")
        and tags.get("area") != "yes"
    )


def platform_walks(
    ways: Sequence[Placed],
    platform_nodes: Set[int],
    closed: Set[int] = frozenset(),
) -> set[int]:
    """The walkways at rail platforms to walk rather than ride: every candidate
    (`is_platform_walk_candidate`, no longer than WAY_MAX_M, not closed) with a node
    within PLATFORM_REACH_M of a platform's node, walking along the candidates. `ways` as
    `links` takes them (only a candidate's coordinates are read); `platform_nodes` the node
    ids of every `railway=platform` way."""
    adjacent: dict[int, list[tuple[int, float]]] = defaultdict(list)
    nodes_of: dict[int, Sequence[int]] = {}
    for osm_id, tags, node_ids, coords in ways:
        if osm_id in closed or len(node_ids) < 2 or not is_platform_walk_candidate(tags):
            continue
        steps = [
            (i, _metres(a, b))
            for i, (a, b) in enumerate(zip(coords, coords[1:], strict=False))
            if a is not None and b is not None
        ]
        if sum(m for _i, m in steps) > WAY_MAX_M:
            continue
        nodes_of[osm_id] = node_ids
        for i, step in steps:
            adjacent[node_ids[i]].append((node_ids[i + 1], step))
            adjacent[node_ids[i + 1]].append((node_ids[i], step))
    best = {node: 0.0 for node in adjacent if node in platform_nodes}
    queue = [(0.0, node) for node in best]
    heapq.heapify(queue)
    while queue:
        metres, node = heapq.heappop(queue)
        if metres > best[node]:
            continue
        for neighbour, step in adjacent[node]:
            total = metres + step
            if total <= PLATFORM_REACH_M and total < best.get(neighbour, math.inf):
                best[neighbour] = total
                heapq.heappush(queue, (total, neighbour))
    return {osm_id for osm_id, node_ids in nodes_of.items() if any(n in best for n in node_ids)}
