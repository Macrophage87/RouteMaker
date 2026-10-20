"""Walk-your-bike links into Metro and MARC stations, and escalators closed to bicycles.

The owner, riding to Shady Grove on 2026-10-20: "Somehow it missed one of the metro
entrances", "This station has a walking tunnel to get to it, not stairs" and "There are
several of these". The footways that lead into a station (its tunnels under the tracks,
the last stretch from the street to its elevator) mostly carry no bicycle tag, so
upstream's transform closes them by class and a route stopped at the last road, or went
the long way round to another side. The owner chose (2026-10-20, "Yes, walk your bike")
to open them at a walk: WMATA lets a bicycle into a station walked, by the elevator.

So, at every station: from its ways in (a `railway=subway_entrance` or
`train_station_entrance`, a street elevator near a station, the station node itself),
the footways with no bicycle tag (`walk_links.is_link_candidate`) lead out to the
nearest bicycle-open ways, within `WALK_MAX_M` along them; each footway on such a walk
becomes a `bicycle=dismount` link, "walk your bike here", as `routemaker.walk_links`'
are (`rm:walk_link`). A walk stops at the first bicycle-open way it meets: it is a way
in, not a way round. Never steps, never a footway a closure rule closes (the CBD's
sidewalks, a military or secured area), an indoor or informal one, an area, or one
longer than `walk_links.WAY_MAX_M`.

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

from .walk_links import MANY, WAY_MAX_M, Placed, bicycle_open, is_link_candidate

# The `rm:no_bicycle` reason for an escalator.
ESCALATOR = "escalator"

# The longest walk from a way in to a bicycle-open way, along the footways (about 800 ft):
# Shady Grove's tunnel under the tracks is about 260 ft, and its walk to the street
# elevator about 200 ft more.
WALK_MAX_M = 250.0
# A footway node this close to a way in starts a walk (about 80 ft): an elevator or an
# entrance is often mapped beside the footway it serves, not on it.
SEED_M = 25.0
# A street elevator counts as a way in within this of a station node (about 1,000 ft).
ELEVATOR_STATION_M = 300.0

_EARTH_M = 6_371_008.8


def is_escalator(tags: dict[str, str]) -> bool:
    return tags.get("highway") == "steps" and tags.get("conveying") not in (None, "no")


def is_way_in(tags: dict[str, str]) -> bool:
    """A node that is a station's own way in, or the station itself."""
    return (
        tags.get("railway") in ("subway_entrance", "train_station_entrance", "station")
        or tags.get("public_transport") == "station"
    )


def is_station(tags: dict[str, str]) -> bool:
    return tags.get("railway") == "station" or tags.get("public_transport") == "station"


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
    """The points walks start from: every entrance and station, and the elevators within
    ELEVATOR_STATION_M of a station (an elevator elsewhere is a building's)."""
    points = [*entrances, *stations]
    points += [e for e in elevators if any(_metres(e, s) <= ELEVATOR_STATION_M for s in stations)]
    return points


class _Grid:
    """Points by a cell about SEED_M across, for the nodes near a way in."""

    def __init__(self, points: Iterable[tuple[float, float]]) -> None:
        self.cells: dict[tuple[int, int], list[tuple[float, float]]] = defaultdict(list)
        for point in points:
            self.cells[self._cell(point)].append(point)

    @staticmethod
    def _cell(point: tuple[float, float]) -> tuple[int, int]:
        # 0.0003 degrees is about 33 m north-south and 26 m east-west here.
        return (math.floor(point[0] / 0.0003), math.floor(point[1] / 0.0003))

    def near(self, point: tuple[float, float], metres: float) -> bool:
        cx, cy = self._cell(point)
        return any(
            _metres(point, other) <= metres
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for other in self.cells.get((cx + dx, cy + dy), ())
        )


def links(
    ways: Sequence[Placed],
    points: Iterable[tuple[float, float]],
    closed: Set[int] = frozenset(),
) -> dict[int, float]:
    """The footways to open as walk-your-bike links into a station, each with the
    shortest walk (metres) it is part of. `ways` as `walk_links.links` takes them (only a
    link candidate's coordinates are read); `points` the ways in (`ways_in`); `closed`
    the ways a closure rule closes."""
    grid = _Grid(points)
    if not grid.cells:
        return {}
    adjacent: dict[int, list[tuple[int, float, int]]] = defaultdict(list)
    lengths: dict[int, float] = {}
    seeds: set[int] = set()
    for osm_id, tags, node_ids, coords in ways:
        if osm_id in closed or len(node_ids) < 2 or not is_link_candidate(tags):
            continue
        length = 0.0
        for i, (node, coord) in enumerate(zip(node_ids, coords, strict=False)):
            if coord is not None and grid.near(coord, SEED_M):
                seeds.add(node)
            if i + 1 < len(node_ids):
                a, b = coord, coords[i + 1]
                if a is None or b is None:
                    continue
                step = _metres(a, b)
                length += step
                adjacent[node].append((node_ids[i + 1], step, osm_id))
                adjacent[node_ids[i + 1]].append((node, step, osm_id))
        lengths[osm_id] = length
    if not seeds:
        return {}

    open_at: dict[int, int] = {}
    for osm_id, tags, node_ids, _coords in ways:
        if osm_id in closed or len(node_ids) < 2 or not bicycle_open(tags):
            continue
        for node in set(node_ids):
            if node in adjacent:
                open_at[node] = osm_id if open_at.get(node, osm_id) == osm_id else MANY

    # From every way in at once: the shortest walk to each node, and the footway it came by.
    best: dict[int, float] = {}
    previous: dict[int, tuple[int, int]] = {}
    queue: list[tuple[float, int]] = []
    for seed in seeds:
        best[seed] = 0.0
        queue.append((0.0, seed))
    heapq.heapify(queue)
    reached: list[int] = []
    while queue:
        metres, node = heapq.heappop(queue)
        if metres > best.get(node, math.inf):
            continue
        if node in open_at:
            reached.append(node)
            continue  # rideable from here: a way in, not a way round
        for neighbour, step, way in adjacent.get(node, ()):
            total = metres + step
            if total <= WALK_MAX_M and total < best.get(neighbour, math.inf):
                best[neighbour] = total
                previous[neighbour] = (node, way)
                heapq.heappush(queue, (total, neighbour))

    found: dict[int, float] = {}
    for end in reached:
        used: list[int] = []
        at = end
        while at in previous:
            at, way = previous[at]
            if way not in used:
                used.append(way)
        if not used or any(lengths[way] > WAY_MAX_M for way in used):
            continue
        for way in used:
            found[way] = min(best[end], found.get(way, best[end]))
    return found
